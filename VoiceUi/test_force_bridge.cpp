#include "force_bridge.hpp"
#include "../../xCoreSDK_cpp-v0.7.1/example/admittance_071/force_input.hpp"

// 只运行真实 ForceInput 和通信线程，不链接 SDK、不连接机械臂。
int main() {
    try {
        admittance_demo::ForceInput input;
        if(!std::getenv("VOICE_TEST_NO_FEEDBACK"))input.publishFeedback(0,0,0,0,0,false);
        voice_force::ForceBridge<admittance_demo::ForceInput> bridge(input);
        std::cout<<"READY"<<std::endl;
        std::string command;
        while(std::getline(std::cin,command)) {
            if(command=="quit")break;
            if(command=="feedback")input.publishFeedback(9.5,14,4.5,12.3,3,true);
            if(command=="calibration")input.publishFeedback(0,4.5,4.5,.5,0,false);
            if(command=="fault")input.publishFeedback(9.5,14,4.5,12.3,8,false);
            if(command=="finish")bridge.finish();
            if(command=="curve")input.enableCurve(12);
            if(command=="advance")for(int i=0;i<1000;++i)input.advance(.001);
            if(command=="unload")input.beginUnload();
            if(command=="close")input.close();
            if(command=="stop")input.requestStop();
            std::cout<<input.requestedForce()<<' '<<input.commandedForce()<<' '
                     <<input.stopRequested()<<std::endl;
        }
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
