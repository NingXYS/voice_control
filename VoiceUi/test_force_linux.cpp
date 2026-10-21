#include "../../xCoreSDK_cpp-v0.7.1/example/admittance_071/force_console.hpp"
#include <cassert>

int main(int argc,char** argv) {
    if(argc==2 && std::string(argv[1])=="--console-lines") {
        runtime_force::ConsoleLines lines;
        for(int i=0;i<1000;++i) {
            std::string line;
            if(lines.poll(line)) {
                std::cout<<line<<std::endl;
                if(line=="quit")return 0;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        return 1;
    }
    if(argc==2 && std::string(argv[1])=="--console-close") {
        admittance_demo::ForceInput input;
        {admittance_demo::ForceConsole console(input);
         std::this_thread::sleep_for(std::chrono::milliseconds(20));}
        return input.acceptsDesiredForce()?1:0;
    }
    admittance_demo::ForceInput input;
    std::atomic<bool> done{false};
    std::thread writer([&]{
        for(int i=1;i<200000;++i)input.publishFeedback(i,i*2.,i*3.,i*4.,i%4,true);
        done.store(true);
    });
    std::size_t checked=0;
    do {
        admittance_demo::ForceInput::Feedback sample;
        if(input.readFeedback(sample)) {
            assert(sample.valid);
            assert(sample.raw==sample.measured*2);
            assert(sample.bias==sample.measured*3);
            assert(sample.elapsed==sample.measured*4);
            assert(sample.phase==static_cast<int>(sample.measured)%4);
            assert(!(sample.sequence&1));
            ++checked;
        }
    }while(!done.load());
    writer.join();
    std::cout<<"coherent_snapshots="<<checked<<std::endl;
    return checked?0:1;
}
