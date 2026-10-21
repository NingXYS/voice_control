#pragma once
// 必须先于 windows.h 引入，避免旧 Winsock 声明冲突。
#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#pragma comment(lib, "Ws2_32.lib")
#else
#include <arpa/inet.h>
#include <fcntl.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>
#endif
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstdint>
#include <iostream>
#include <locale>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>

namespace voice_force {
#ifdef _WIN32
using Socket = SOCKET;
constexpr Socket invalidSocket = INVALID_SOCKET;
inline void closeSocket(Socket s) { closesocket(s); }
inline void nonblocking(Socket s) {
    u_long yes=1;
    if(ioctlsocket(s,FIONBIO,&yes)!=0)throw std::runtime_error("voice force nonblocking");
}
#else
using Socket = int;
constexpr Socket invalidSocket = -1;
inline void closeSocket(Socket s) { ::close(s); }
inline void nonblocking(Socket s) {
    const int flags=fcntl(s,F_GETFL,0);
    if(flags<0 || fcntl(s,F_SETFL,flags|O_NONBLOCK)<0)throw std::runtime_error("voice force nonblocking");
}
#endif
inline std::string setting(const char* name,const char* fallback="") {
    const char* value=std::getenv(name);
    return value?value:fallback;
}
inline bool validToken(const std::string& token) {
    if(token.size()<32 || token.size()>128)return false;
    for(unsigned char c:token)
        if(!((c>='A'&&c<='Z')||(c>='a'&&c<='z')||(c>='0'&&c<='9')||c=='_'||c=='-'))return false;
    return true;
}
inline bool ready(Socket s,bool write,int milliseconds) {
#ifndef _WIN32
    if(s<0 || s>=FD_SETSIZE)return false;
#endif
    fd_set set;FD_ZERO(&set);FD_SET(s,&set);
    timeval wait{milliseconds/1000,(milliseconds%1000)*1000};
    return select(static_cast<int>(s+1),write?nullptr:&set,write?&set:nullptr,nullptr,&wait)>0;
}

// 仅后台线程读写套接字；只更新当前会话对象，不调用 SDK、不推进实时斜坡。
template<class ForceInput> class ForceBridge {
public:
    explicit ForceBridge(ForceInput& input):input_(input),token_(setting("VOICE_FORCE_TOKEN")) {
        if(token_.empty())return;
        if(!validToken(token_))throw std::runtime_error("VOICE_FORCE_TOKEN invalid (32..128 URL-safe characters)");
        const auto portText=setting("VOICE_FORCE_PORT","19071");
        std::size_t consumed=0;
        const int port=std::stoi(portText,&consumed);
        if(consumed!=portText.size() || port<1 || port>65535)throw std::runtime_error("VOICE_FORCE_PORT invalid");
        sockaddr_in address{};address.sin_family=AF_INET;address.sin_port=htons(static_cast<unsigned short>(port));
        const auto bind=setting("VOICE_FORCE_BIND","127.0.0.1");
#ifdef _WIN32
        WSADATA data{};
        if(WSAStartup(MAKEWORD(2,2),&data)!=0)throw std::runtime_error("voice force WSAStartup");
        winsock_=true;
#endif
        try {
            if(inet_pton(AF_INET,bind.c_str(),&address.sin_addr)!=1)throw std::runtime_error("VOICE_FORCE_BIND requires an IPv4 address");
            sessionId_=std::to_string(std::chrono::system_clock::now().time_since_epoch().count());
            listener_=socket(AF_INET,SOCK_STREAM,IPPROTO_TCP);
            if(listener_==invalidSocket)throw std::runtime_error("voice force socket");
#ifdef _WIN32
            const int exclusive=1;
            if(setsockopt(listener_,SOL_SOCKET,SO_EXCLUSIVEADDRUSE,reinterpret_cast<const char*>(&exclusive),sizeof(exclusive))!=0)
                throw std::runtime_error("voice force exclusive bind");
#else
            const int reuse=1;
            if(setsockopt(listener_,SOL_SOCKET,SO_REUSEADDR,&reuse,sizeof(reuse))!=0)
                throw std::runtime_error("voice force reuse address");
#endif
            if(::bind(listener_,reinterpret_cast<sockaddr*>(&address),sizeof(address))!=0 || listen(listener_,4)!=0)
                throw std::runtime_error("voice force bind/listen (another session may own this port)");
            nonblocking(listener_);
            worker_=std::thread([this]{work();});
            std::cout<<"Voice force bridge: "<<bind<<':'<<port<<" (authenticated force/status only).\n";
        } catch(...) {cleanup();throw;}
    }
    ~ForceBridge(){finish();}
    ForceBridge(const ForceBridge&)=delete;
    ForceBridge& operator=(const ForceBridge&)=delete;
    void finish() noexcept {
        finished_.store(true);
        if(worker_.joinable())worker_.join();
        cleanup();
    }

    std::string handle(const std::string& line) {
        const auto reject=[](const char* reason){return std::string("{\"ok\":false,\"error\":\"")+reason+"\"}\n";};
        if(line.size()>256 || line.find_first_of("\r\n\0",0,3)!=std::string::npos)return reject("invalid");
        std::istringstream in(line);in.imbue(std::locale::classic());
        std::string token,command,extra;
        if(!(in>>token>>command) || token!=token_)return reject("unauthorized");
        if(command=="status") {
            if(in>>extra)return reject("invalid");
        } else if(command=="force" || command=="adjust") {
            double value=0;
            if(!(in>>value) || in>>extra || !std::isfinite(value))return reject("invalid");
            typename ForceInput::Feedback feedback;
            const bool haveFeedback=input_.readFeedback(feedback);
            if(!haveFeedback || feedbackAge(feedback)>1000)return reject("feedback_not_ready");
            if(!input_.acceptsDesiredForce() || finished_.load() || feedback.phase>=4)return reject("closed");
            if(command=="adjust") {
                if(value==0 || std::abs(value)>ForceInput::maxTargetForce-ForceInput::minTargetForce)return reject("range");
                // 增减基于当前曲线/手动请求值，不使用语音进程中的历史缓存。
                value+=input_.requestedForce();
            }
            if(!input_.setDesiredForce(value))return reject("range_or_closed");
        } else return reject("unsupported");
        typename ForceInput::Feedback feedback;
        const bool haveFeedback=input_.readFeedback(feedback);
        const auto age=haveFeedback?feedbackAge(feedback):0;
        const bool valid=haveFeedback && feedback.valid && age<=1000;
        static constexpr const char* phases[]={"calibration","force-settle","align-first-xy","curve-track","unload","brake","lift","done","fault"};
        const char* phase=haveFeedback && feedback.phase>=0 && feedback.phase<9?phases[feedback.phase]:"waiting-callback";
        std::ostringstream out;out.imbue(std::locale::classic());out.precision(12);
        out<<"{\"ok\":true,\"requested_n\":"<<input_.requestedForce()
           <<",\"target_n\":"<<input_.commandedForce()
           <<",\"source\":\""<<(input_.manualOverride()?"manual":"curve")<<"\""
           <<",\"measured_n\":";
        if(valid)out<<feedback.measured;else out<<"null";
        out<<",\"raw_n\":";
        if(haveFeedback && std::isfinite(feedback.raw))out<<feedback.raw;else out<<"null";
        out<<",\"bias_n\":";
        if(haveFeedback && std::isfinite(feedback.bias))out<<feedback.bias;else out<<"null";
        out<<",\"controller_time_s\":";
        if(haveFeedback && std::isfinite(feedback.elapsed))out<<feedback.elapsed;else out<<"null";
        out<<",\"phase\":\""<<phase<<"\",\"sample_valid\":"<<(valid?"true":"false")
           <<",\"sample_seq\":"<<(haveFeedback?feedback.sequence:0)
           <<",\"sample_age_ms\":"<<age
           <<",\"accepting_force\":"<<(input_.acceptsDesiredForce() && haveFeedback && age<=1000 && feedback.phase<4?"true":"false")
           <<",\"min_target_n\":"<<ForceInput::minTargetForce
           <<",\"max_target_n\":"<<ForceInput::maxTargetForce
           <<",\"slew_rate_n_s\":"<<ForceInput::slewRate
           <<",\"session_id\":\""<<sessionId_<<"\",\"protocol\":2}\n";
        return out.str();
    }

private:
    static std::int64_t milliseconds() {
        return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
    }
    std::int64_t feedbackAge(const typename ForceInput::Feedback& feedback) const {
        return feedback.sequence==observedSequence_.load()?std::max<std::int64_t>(0,milliseconds()-observedAt_.load()):0;
    }
    void observeFeedback() {
        typename ForceInput::Feedback feedback;
        if(input_.readFeedback(feedback) && feedback.sequence!=observedSequence_.load()) {
            observedAt_.store(milliseconds());observedSequence_.store(feedback.sequence);
        }
    }
    void cleanup() noexcept {
        if(listener_!=invalidSocket){closeSocket(listener_);listener_=invalidSocket;}
#ifdef _WIN32
        if(winsock_){WSACleanup();winsock_=false;}
#endif
    }
    void serve(Socket client) {
        nonblocking(client);
        std::string line;
        const auto deadline=std::chrono::steady_clock::now()+std::chrono::milliseconds(250);
        while(!finished_.load() && std::chrono::steady_clock::now()<deadline) {
            if(!ready(client,false,10))continue;
            char byte=0;
            const int count=static_cast<int>(recv(client,&byte,1,0));
            if(count<=0)return;
            if(byte=='\n') {
                if(finished_.load())return;
                const auto reply=handle(line);
                std::size_t sent=0;
                while(sent<reply.size() && !finished_.load() && std::chrono::steady_clock::now()<deadline) {
                    if(!ready(client,true,10))continue;
#ifdef _WIN32
                    const int flags=0;
#else
                    const int flags=MSG_NOSIGNAL;
#endif
                    const int countSent=static_cast<int>(send(client,reply.data()+sent,static_cast<int>(reply.size()-sent),flags));
                    if(countSent<=0)return;
                    sent+=static_cast<std::size_t>(countSent);
                }
                return;
            }
            if(line.size()>=256)return;
            line+=byte;
        }
    }
    void work() noexcept {
        while(!finished_.load()) {
            observeFeedback();
            if(!ready(listener_,false,20))continue;
            Socket client=accept(listener_,nullptr,nullptr);
            if(client==invalidSocket)continue;
            try {serve(client);}catch(...){/* 连接失败只保持原目标，不补发命令。 */}
            closeSocket(client);
        }
    }
    ForceInput& input_;
    std::string token_,sessionId_;
    std::atomic<std::uint64_t> observedSequence_{0};
    std::atomic<std::int64_t> observedAt_{0};
    Socket listener_=invalidSocket;
    std::atomic<bool> finished_{false};
    std::thread worker_;
#ifdef _WIN32
    bool winsock_=false;
#endif
};
} // namespace voice_force
