#pragma once
#include <iostream>
#include <stdexcept>
#ifdef _WIN32
#include <windows.h>
#include <mmsystem.h>
#endif
namespace rt_probe {
class TimerResolution {
public:
    explicit TimerResolution(bool enable) {
#ifdef _WIN32
        if(enable && timeBeginPeriod(1)!=TIMERR_NOERROR)
            throw std::runtime_error("timeBeginPeriod(1) failed");
        enabled_=enable;
#else
        // Linux 无 Windows 全局计时器周期；保留旧参数但不改调度或 SDK 周期。
        if(enable)std::cout<<"--timer-1ms: Windows-only timer request ignored on Linux; SDK callback limits unchanged.\n";
#endif
    }
    ~TimerResolution() {
#ifdef _WIN32
        if(enabled_)timeEndPeriod(1);
#endif
    }
    TimerResolution(const TimerResolution&)=delete;
    TimerResolution& operator=(const TimerResolution&)=delete;
private:
#ifdef _WIN32
    bool enabled_=false;
#endif
};
} // namespace rt_probe
