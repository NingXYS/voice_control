#pragma once
#include <chrono>
#include <iostream>
#include <string>
#include <thread>
#ifdef _WIN32
#include <conio.h>
#else
#include <poll.h>
#include <unistd.h>
#endif

namespace runtime_force {
// 不更改终端模式；Linux 管道和终端都只在可读时取一个字符，退出不等 Enter。
class ConsoleLines {
public:
    bool poll(std::string& line) {
        for(int i=0;i<512;++i) {
#ifdef _WIN32
            if(!_kbhit())return false;
            const int value=_getch();
            if(value==0 || value==224){if(_kbhit())_getch();continue;}
            const char byte=static_cast<char>(value);
            if(byte=='\b'){if(!pending_.empty())pending_.pop_back();continue;}
            std::cout<<byte<<std::flush;
#else
            pollfd descriptor{STDIN_FILENO,POLLIN,0};
            if(::poll(&descriptor,1,0)<=0 || !(descriptor.revents&POLLIN))return false;
            char byte=0;
            if(::read(STDIN_FILENO,&byte,1)!=1)return false;
#endif
            if(byte=='\n' || byte=='\r') {
                if(overflow_){pending_.clear();overflow_=false;continue;}
                if(pending_.empty())continue;
                line.swap(pending_);pending_.clear();return true;
            }
            if(pending_.size()<256 && !overflow_)pending_+=byte;
            else {pending_.clear();overflow_=true;}
        }
        return false;
    }
private:
    std::string pending_;
    bool overflow_=false;
};
} // namespace runtime_force
