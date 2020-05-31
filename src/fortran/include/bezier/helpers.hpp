// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     https://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#ifndef BEZIER_HELPERS_HPP
#define BEZIER_HELPERS_HPP

#include "bezier/helpers.h"
#include "xtensor/xtensor.hpp"

#include <array>
#include <tuple>
#include <vector>

namespace bezier {

double cross_product(
    const std::vector<double>& vec0, const std::vector<double>& vec1)
{
    double result;
    BEZ_cross_product(vec0.data(), vec1.data(), &result);
    return result;
}

template <size_t N>
std::array<double, 4> bbox(const xt::xtensor_fixed<double, xt::xshape<2, N>,
    xt::layout_type::column_major>& nodes)
{
    double left, right, bottom, top;
    int num_nodes = nodes.shape(1) BEZ_bbox(
        &num_nodes, nodes.data(), &left, &right, &bottom, &top);
    return { left, right, bottom, top };
}

std::tuple<double, bool> wiggle_interval(const double& value)
{
    double result;
    bool success;
    BEZ_wiggle_interval(&value, &result, &success);
    return std::make_tuple(result, success);
}

// TODO: contains_nd
// TODO: vector_close

bool in_interval(const double& value, const double& start, const double& end)
{
    return BEZ_in_interval(&value, &start, &end);
}

// TODO: simple_convex_hull
// TODO: polygon_collide
}

#endif /* BEZIER_HELPERS_HPP */
