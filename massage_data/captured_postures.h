#pragma once

#include <array>
#ifndef _USE_MATH_DEFINES
#define _USE_MATH_DEFINES
#endif
#include <cmath>

inline const std::array<std::array<double, 6>, 2> capturedPostures = {{
  {-0.009744, -0.724420, 0.463627,
   -160.504 * M_PI / 180.0, 32.905 * M_PI / 180.0,
   116.128 * M_PI / 180.0},  // P0
  {-0.062094, -0.667287, 0.390444,
   -160.731 * M_PI / 180.0, 24.005 * M_PI / 180.0,
   112.899 * M_PI / 180.0}   // P1
}};
