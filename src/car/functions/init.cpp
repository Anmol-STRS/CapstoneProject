#include <Init.hpp>
#include <iostream>
#include <string>

void CHECKIFWORKING::returnName(const std::string& name) {
    if (name.empty()) {
        std::cout << "Found None\n";
        return;
    }
    std::cout << "Working code for " << name << '\n';
}
