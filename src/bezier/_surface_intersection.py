# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Private helper methods for :mod:`bezier.surface`.

As a convention, the functions defined here with a leading underscore
(e.g. :func:`_newton_refine`) have a special meaning.

Each of these functions have a Cython speedup with the exact same
interface which calls out to a Fortran implementation. The speedup
will be used if the extension can be built. The name **without** the
leading underscore will be surfaced as the actual interface (e.g.
``newton_refine``) whether that is the pure Python implementation
or the speedup.
"""

import collections
import itertools

import numpy as np
import six

from bezier import _algebraic_intersection
from bezier import _geometric_intersection
from bezier import _helpers
from bezier import _intersection_helpers
from bezier import _surface_helpers
try:
    from bezier import _surface_intersection_speedup
except ImportError:  # pragma: NO COVER
    _surface_intersection_speedup = None


MAX_LOCATE_SUBDIVISIONS = 20
LOCATE_EPS = 2.0**(-47)
INTERSECTION_T = _geometric_intersection.BoxIntersectionType.INTERSECTION


def newton_refine_solve(jac_both, x_val, surf_x, y_val, surf_y):
    r"""Helper for :func:`newton_refine`.

    We have a system:

    .. code-block:: rest

       [A C][ds] = [E]
       [B D][dt]   [F]

    This is not a typo, ``A->B->C->D`` matches the data in ``jac_both``.
    We solve directly rather than using a linear algebra utility:

    .. code-block:: rest

       ds = (D E - C F) / (A D - B C)
       dt = (A F - B E) / (A D - B C)

    Args:
        jac_both (numpy.ndarray): A 1x4 matrix of entries in a Jacobian.
        x_val (float): An ``x``-value we are trying to reach.
        surf_x (float): The actual ``x``-value we are currently at.
        y_val (float): An ``y``-value we are trying to reach.
        surf_y (float): The actual ``x``-value we are currently at.

    Returns:
        Tuple[float, float]: The pair of values the solve the
         linear system.
    """
    a_val, b_val, c_val, d_val = jac_both[0, :]
    #       and
    e_val = x_val - surf_x
    f_val = y_val - surf_y
    # Now solve:
    denom = a_val * d_val - b_val * c_val
    delta_s = (d_val * e_val - c_val * f_val) / denom
    delta_t = (a_val * f_val - b_val * e_val) / denom
    return delta_s, delta_t


def _newton_refine(nodes, degree, x_val, y_val, s, t):
    r"""Refine a solution to :math:`B(s, t) = p` using Newton's method.

    .. note::

       There is also a Fortran implementation of this function, which
       will be used if it can be built.

    Computes updates via

    .. math::

       \left[\begin{array}{c}
           0 \\ 0 \end{array}\right] \approx
           \left(B\left(s_{\ast}, t_{\ast}\right) -
           \left[\begin{array}{c} x \\ y \end{array}\right]\right) +
           \left[\begin{array}{c c}
               B_s\left(s_{\ast}, t_{\ast}\right) &
               B_t\left(s_{\ast}, t_{\ast}\right) \end{array}\right]
           \left[\begin{array}{c}
               \Delta s \\ \Delta t \end{array}\right]

    For example, (with weights
    :math:`\lambda_1 = 1 - s - t, \lambda_2 = s, \lambda_3 = t`)
    consider the surface

    .. math::

       B(s, t) =
           \left[\begin{array}{c} 0 \\ 0 \end{array}\right] \lambda_1^2 +
           \left[\begin{array}{c} 1 \\ 0 \end{array}\right]
               2 \lambda_1 \lambda_2 +
           \left[\begin{array}{c} 2 \\ 0 \end{array}\right] \lambda_2^2 +
           \left[\begin{array}{c} 2 \\ 1 \end{array}\right]
               2 \lambda_1 \lambda_3 +
           \left[\begin{array}{c} 2 \\ 2 \end{array}\right]
               2 \lambda_2 \lambda_1 +
           \left[\begin{array}{c} 0 \\ 2 \end{array}\right] \lambda_3^2

    and the point
    :math:`B\left(\frac{1}{4}, \frac{1}{2}\right) =
    \frac{1}{4} \left[\begin{array}{c} 5 \\ 5 \end{array}\right]`.

    Starting from the **wrong** point
    :math:`s = \frac{1}{2}, t = \frac{1}{4}`, we have

    .. math::

       \begin{align*}
       \left[\begin{array}{c} x \\ y \end{array}\right] -
          B\left(\frac{1}{2}, \frac{1}{4}\right) &= \frac{1}{4}
          \left[\begin{array}{c} -1 \\ 2 \end{array}\right] \\
       DB\left(\frac{1}{2}, \frac{1}{4}\right) &= \frac{1}{2}
           \left[\begin{array}{c c} 3 & 2 \\ 1 & 6 \end{array}\right] \\
       \Longrightarrow \left[\begin{array}{c}
           \Delta s \\ \Delta t \end{array}\right] &= \frac{1}{32}
           \left[\begin{array}{c} -10 \\ 7 \end{array}\right]
       \end{align*}

    .. image:: images/newton_refine_surface.png
       :align: center

    .. testsetup:: newton-refine-surface

       import numpy as np
       import bezier
       from bezier._surface_intersection import newton_refine

    .. doctest:: newton-refine-surface

       >>> nodes = np.asfortranarray([
       ...     [0.0, 0.0],
       ...     [1.0, 0.0],
       ...     [2.0, 0.0],
       ...     [2.0, 1.0],
       ...     [2.0, 2.0],
       ...     [0.0, 2.0],
       ... ])
       >>> surface = bezier.Surface(nodes, degree=2)
       >>> surface.is_valid
       True
       >>> (x_val, y_val), = surface.evaluate_cartesian(0.25, 0.5)
       >>> x_val, y_val
       (1.25, 1.25)
       >>> s, t = 0.5, 0.25
       >>> new_s, new_t = newton_refine(nodes, 2, x_val, y_val, s, t)
       >>> 32 * (new_s - s)
       -10.0
       >>> 32 * (new_t - t)
       7.0

    .. testcleanup:: newton-refine-surface

       import make_images
       make_images.newton_refine_surface(
           surface, x_val, y_val, s, t, new_s, new_t)

    Args:
        nodes (numpy.ndarray): Array of nodes in a surface.
        degree (int): The degree of the surface.
        x_val (float): The :math:`x`-coordinate of a point
            on the surface.
        y_val (float): The :math:`y`-coordinate of a point
            on the surface.
        s (float): Approximate :math:`s`-value to be refined.
        t (float): Approximate :math:`t`-value to be refined.

    Returns:
        Tuple[float, float]: The refined :math:`s` and :math:`t` values.
    """
    lambda1 = 1.0 - s - t
    (surf_x, surf_y), = _surface_helpers.evaluate_barycentric(
        nodes, degree, lambda1, s, t)
    if surf_x == x_val and surf_y == y_val:
        # No refinement is needed.
        return s, t

    # NOTE: This function assumes ``dimension==2`` (i.e. since ``x, y``).
    jac_nodes = _surface_helpers.jacobian_both(nodes, degree, 2)

    # The degree of the jacobian is one less.
    jac_both = _surface_helpers.evaluate_barycentric(
        jac_nodes, degree - 1, lambda1, s, t)

    # The first column of the jacobian matrix is B_s (i.e. the
    # left-most values in ``jac_both``).
    delta_s, delta_t = newton_refine_solve(
        jac_both, x_val, surf_x, y_val, surf_y)
    return s + delta_s, t + delta_t


def update_locate_candidates(
        candidate, next_candidates, x_val, y_val, degree):
    """Update list of candidate surfaces during geometric search for a point.

    .. note::

       This is used **only** as a helper for :func:`locate_point`.

    Checks if the point ``(x_val, y_val)`` is contained in the ``candidate``
    surface. If not, this function does nothing. If the point is contaned,
    the four subdivided surfaces from ``candidate`` are added to
    ``next_candidates``.

    Args:
        candidate (Tuple[float, float, float, numpy.ndarray]): A 4-tuple
            describing a surface and its centroid / width. Contains

            * Three times centroid ``x``-value
            * Three times centroid ``y``-value
            * "Width" of parameter space for the surface
            * Control points for the surface
        next_candidates (list): List of "candidate" sub-surfaces that may
            contain the point being located.
        x_val (float): The ``x``-coordinate being located.
        y_val (float): The ``y``-coordinate being located.
        degree (int): The degree of the surface.
    """
    centroid_x, centroid_y, width, candidate_nodes = candidate
    point = np.asfortranarray([[x_val, y_val]])
    if not _helpers.contains_nd(candidate_nodes, point):
        return

    nodes_a, nodes_b, nodes_c, nodes_d = _surface_helpers.subdivide_nodes(
        candidate_nodes, degree)

    half_width = 0.5 * width
    next_candidates.extend((
        (
            centroid_x - half_width,
            centroid_y - half_width,
            half_width,
            nodes_a,
        ), (
            centroid_x,
            centroid_y,
            -half_width,
            nodes_b,
        ), (
            centroid_x + width,
            centroid_y - half_width,
            half_width,
            nodes_c,
        ), (
            centroid_x - half_width,
            centroid_y + width,
            half_width,
            nodes_d,
        ),
    ))


def mean_centroid(candidates):
    """Take the mean of all centroids in set of reference triangles.

    .. note::

       This is used **only** as a helper for :func:`locate_point`.

    Args:
        candidates (List[Tuple[float, float, float, numpy.ndarray]): List of
            4-tuples, each of which has been produced by :func:`locate_point`.
            Each 4-tuple contains

            * Three times centroid ``x``-value
            * Three times centroid ``y``-value
            * "Width" of a parameter space for a surface
            * Control points for a surface

            We only use the first two values, which are triple the desired
            value so that we can put off division by three until summing in
            our average. We don't use the other two values, they are just an
            artifact of the way ``candidates`` is constructed by the caller.

    Returns:
        Tuple[float, float]: The mean of all centroids.
    """
    sum_x = 0.0
    sum_y = 0.0
    for centroid_x, centroid_y, _, _ in candidates:
        sum_x += centroid_x
        sum_y += centroid_y

    denom = 3.0 * len(candidates)
    return sum_x / denom, sum_y / denom


def _locate_point(nodes, degree, x_val, y_val):
    r"""Locate a point on a surface.

    .. note::

       There is also a Fortran implementation of this function, which
       will be used if it can be built.

    Does so by recursively subdividing the surface and rejecting
    sub-surfaces with bounding boxes that don't contain the point.
    After the sub-surfaces are sufficiently small, uses Newton's
    method to narrow in on the pre-image of the point.

    Args:
        nodes (numpy.ndarray): Control points for B |eacute| zier surface
            (assumed to be two-dimensional).
        degree (int): The degree of the surface.
        x_val (float): The :math:`x`-coordinate of a point
            on the surface.
        y_val (float): The :math:`y`-coordinate of a point
            on the surface.

    Returns:
        Optional[Tuple[float, float]]: The :math:`s` and :math:`t`
        values corresponding to ``x_val`` and ``y_val`` or
        :data:`None` if the point is not on the ``surface``.
    """
    # We track the centroid rather than base_x/base_y/width (by storing triple
    # the centroid -- to avoid division by three until needed). We also need
    # to track the width (or rather, just the sign of the width).
    candidates = [(1.0, 1.0, 1.0, nodes)]
    for _ in six.moves.xrange(MAX_LOCATE_SUBDIVISIONS + 1):
        next_candidates = []
        for candidate in candidates:
            update_locate_candidates(
                candidate, next_candidates, x_val, y_val, degree)

        candidates = next_candidates

    if not candidates:
        return None

    # We take the average of all centroids from the candidates
    # that may contain the point.
    s_approx, t_approx = mean_centroid(candidates)
    s, t = newton_refine(
        nodes, degree, x_val, y_val, s_approx, t_approx)

    actual = _surface_helpers.evaluate_barycentric(
        nodes, degree, 1.0 - s - t, s, t)
    expected = np.asfortranarray([[x_val, y_val]])
    if not _helpers.vector_close(actual, expected, eps=LOCATE_EPS):
        s, t = newton_refine(
            nodes, degree, x_val, y_val, s, t)
    return s, t


def same_intersection(intersection1, intersection2, wiggle=0.5**40):
    """Check if two intersections are close to machine precision.

    .. note::

       This is a helper used only by :func:`verify_duplicates`, which in turn
       is only used by :meth:`.Surface.intersect`.

    Args:
        intersection1 (.Intersection): The first intersection.
        intersection2 (.Intersection): The second intersection.
        wiggle (Optional[float]): The amount of relative error allowed
            in parameter values.

    Returns:
        bool: Indicates if the two intersections are the same to
        machine precision.
    """
    # pylint: disable=protected-access
    if intersection1.index_first != intersection2.index_first:
        return False
    if intersection1.index_second != intersection2.index_second:
        return False
    # pylint: enable=protected-access

    return np.allclose(
        [intersection1.s, intersection1.t],
        [intersection2.s, intersection2.t],
        atol=0.0, rtol=wiggle)


def verify_duplicates(duplicates, uniques):
    """Verify that a set of intersections had expected duplicates.

    .. note::

       This is a helper used only by :meth:`.Surface.intersect`.

    Args:
        duplicates (List[.Intersection]): List of intersections
            corresponding to duplicates that were filtered out.
        uniques (List[.Intersection]): List of "final" intersections
            with duplicates filtered out.

    Raises:
        ValueError: If the ``uniques`` are not actually all unique.
        ValueError: If one of the ``duplicates`` does not correspond to
            an intersection in ``uniques``.
        ValueError: If a duplicate occurs only once but does not have
            exactly one of ``s`` and ``t`` equal to ``0.0``.
        ValueError: If a duplicate occurs three times but does not have
            exactly both ``s == t == 0.0``.
        ValueError: If a duplicate occurs a number other than one or three
            times.
    """
    for uniq1, uniq2 in itertools.combinations(uniques, 2):
        if same_intersection(uniq1, uniq2):
            raise ValueError('Non-unique intersection')

    counter = collections.Counter()
    for dupe in duplicates:
        matches = []
        for index, uniq in enumerate(uniques):
            if same_intersection(dupe, uniq):
                matches.append(index)

        if len(matches) != 1:
            raise ValueError('Duplicate not among uniques', dupe)

        matched = matches[0]
        counter[matched] += 1

    for index, count in six.iteritems(counter):
        uniq = uniques[index]
        if count == 1:
            if (uniq.s, uniq.t).count(0.0) != 1:
                raise ValueError('Count == 1 should be a single corner', uniq)
        elif count == 3:
            if (uniq.s, uniq.t) != (0.0, 0.0):
                raise ValueError('Count == 3 should be a double corner', uniq)
        else:
            raise ValueError('Unexpected duplicate count', count)


def add_intersection(  # pylint: disable=too-many-arguments
        index1, s, index2, t, edge_nodes1, edge_nodes2, duplicates,
        intersections, unused, all_types):
    """Create an :class:`Intersection` and append.

    The intersection will be classified as either a duplicate or a valid
    intersection and appended to one of ``duplicates`` or ``intersections``
    depending on that classification.

    Args:
        index1 (int): The index (among 0, 1, 2) of the first edge in the
            intersection.
        s (float): The parameter along the first curve of the intersection.
        index2 (int): The index (among 0, 1, 2) of the second edge in the
            intersection.
        t (float): The parameter along the second curve of the intersection.
        edge_nodes1 (Tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray]): The
            nodes of the three edges of the first surface being intersected.
        edge_nodes2 (Tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray]): The
            nodes of the three edges of the second surface being intersected.
        duplicates (List[.Intersection]): List of duplicate intersections.
        intersections (List[.Intersection]): List of "accepted" (i.e.
            non-duplicate) intersections.
        unused (List[.Intersection]): Intersections that won't be used,
            such as a tangent intersection along an edge. This is
            provided for the case where the output will be verified.
        all_types (Set[.IntersectionClassification]): The set of all
            intersection classifications encountered among the intersections
            for the given surface-surface pair.
    """
    edge_end, intersection_args = _surface_helpers.handle_ends(
        index1, s, index2, t)
    if edge_end:
        intersection = _intersection_helpers.Intersection(
            *intersection_args)
        duplicates.append(intersection)
    else:
        intersection = _intersection_helpers.Intersection(
            index1, s, index2, t)
        # Classify the intersection.
        interior = _surface_helpers.classify_intersection(
            intersection, edge_nodes1, edge_nodes2)
        all_types.add(interior)
        intersection.interior_curve = interior
        # Only keep the intersections which are ``ACCEPTABLE``.
        if interior == _surface_helpers.IntersectionClassification.FIRST:
            intersections.append(intersection)
        elif interior == _surface_helpers.IntersectionClassification.SECOND:
            intersections.append(intersection)
        else:
            unused.append(intersection)


def surface_intersections(edge_nodes1, edge_nodes2, all_intersections):
    """Find all intersections among edges of two surfaces.

    This treats intersections which have ``s == 1.0`` or ``t == 1.0``
    as duplicates. The duplicates may be checked by the caller, e.g.
    by :func:`verify_duplicates`.

    Args:
        edge_nodes1 (Tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray]): The
            nodes of the three edges of the first surface being intersected.
        edge_nodes2 (Tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray]): The
            nodes of the three edges of the second surface being intersected.
        all_intersections (Callable): A helper that intersects B |eacute| zier
            curves. Takes the nodes of each curve as input and returns an
            array (``N x 2``) of intersections.

    Returns:
        Tuple[list, list, list, set]: 4-tuple of

        * The actual "unique" :class:`Intersection`-s
        * Duplicate :class:`Intersection`-s encountered (these will be
          corner intersections)
        * Intersections that won't be used, such as a tangent intersection
          along an edge
        * All the intersection classifications encountered
    """
    all_types = set()
    intersections = []
    duplicates = []
    unused = []
    for index1, nodes1 in enumerate(edge_nodes1):
        for index2, nodes2 in enumerate(edge_nodes2):
            st_vals = all_intersections(nodes1, nodes2)
            for s, t in st_vals:
                add_intersection(
                    index1, s, index2, t, edge_nodes1, edge_nodes2,
                    duplicates, intersections, unused, all_types)

    return intersections, duplicates, unused, all_types


def generic_intersect(
        nodes1, degree1, nodes2, degree2, verify, all_intersections):
    r"""Find all intersections among edges of two surfaces.

    This treats intersections which have ``s == 1.0`` or ``t == 1.0``
    as duplicates. The duplicates will be checked by :func:`verify_duplicates`
    if ``verify`` is :data:`True`.

    Args:
        nodes1 (numpy.ndarray): The nodes defining the first surface in
            the intersection (assumed in :math:\mathbf{R}^2`).
        degree1 (int): The degree of the surface given by ``nodes1``.
        nodes2 (numpy.ndarray): The nodes defining the second surface in
            the intersection (assumed in :math:\mathbf{R}^2`).
        degree2 (int): The degree of the surface given by ``nodes2``.
        verify (Optional[bool]): Indicates if duplicate intersections
            should be checked.
        all_intersections (Callable): A helper that intersects B |eacute| zier
            curves. Takes the nodes of each curve as input and returns an
            array (``N x 2``) of intersections.

    Returns:
        Tuple[Optional[list], Optional[bool], tuple]: 3-tuple of

        * List of "edge info" lists. Each list represents a curved polygon
          and contains 3-tuples of edge index, start and end (see the
          output of :func:`ends_to_curve`).
        * "Contained" boolean. If not :data:`None`, indicates
          that one of the surfaces is contained in the other.
        * The nodes of three edges of the first surface being intersected
          followed by the nodes of the three edges of the second.
    """
    bbox_int = _geometric_intersection.bbox_intersect(nodes1, nodes2)
    if bbox_int != INTERSECTION_T:
        return [], None, ()

    # We need **all** edges (as nodes).
    edge_nodes1 = _surface_helpers.compute_edge_nodes(nodes1, degree1)
    edge_nodes2 = _surface_helpers.compute_edge_nodes(nodes2, degree2)

    # Run through **all** pairs of edges.
    intersections, duplicates, unused, all_types = surface_intersections(
        edge_nodes1, edge_nodes2, all_intersections)

    # Verify duplicates if need be.
    if verify:
        verify_duplicates(duplicates, intersections + unused)

    edge_infos, contained = _surface_helpers.combine_intersections(
        intersections, nodes1, degree1, nodes2, degree2, all_types)
    if edge_infos is None or edge_infos == []:
        return edge_infos, contained, ()

    return edge_infos, contained, edge_nodes1 + edge_nodes2


def _geometric_intersect(nodes1, degree1, nodes2, degree2, verify):
    r"""Find all intersections among edges of two surfaces.

    .. note::

       There is also a Fortran implementation of this function, which
       will be used if it can be built.

    Uses :func:`generic_intersect` with the
    :attr:`~.IntersectionStrategy.GEOMETRIC` intersection strategy.

    Args:
        nodes1 (numpy.ndarray): The nodes defining the first surface in
            the intersection (assumed in :math:\mathbf{R}^2`).
        degree1 (int): The degree of the surface given by ``nodes1``.
        nodes2 (numpy.ndarray): The nodes defining the second surface in
            the intersection (assumed in :math:\mathbf{R}^2`).
        degree2 (int): The degree of the surface given by ``nodes2``.
        verify (Optional[bool]): Indicates if duplicate intersections
            should be checked.

    Returns:
        Tuple[Optional[list], Optional[bool], tuple]: 3-tuple of

        * List of "edge info" lists. Each list represents a curved polygon
          and contains 3-tuples of edge index, start and end (see the
          output of :func:`ends_to_curve`).
        * "Contained" boolean. If not :data:`None`, indicates
          that one of the surfaces is contained in the other.
        * The nodes of three edges of the first surface being intersected
          followed by the nodes of the three edges of the second.
    """
    all_intersections = _geometric_intersection.all_intersections
    return generic_intersect(
        nodes1, degree1, nodes2, degree2, verify, all_intersections)


def algebraic_intersect(nodes1, degree1, nodes2, degree2, verify):
    r"""Find all intersections among edges of two surfaces.

    Uses :func:`generic_intersect` with the
    :attr:`~.IntersectionStrategy.ALGEBRAIC` intersection strategy.

    Args:
        nodes1 (numpy.ndarray): The nodes defining the first surface in
            the intersection (assumed in :math:\mathbf{R}^2`).
        degree1 (int): The degree of the surface given by ``nodes1``.
        nodes2 (numpy.ndarray): The nodes defining the second surface in
            the intersection (assumed in :math:\mathbf{R}^2`).
        degree2 (int): The degree of the surface given by ``nodes2``.
        verify (Optional[bool]): Indicates if duplicate intersections
            should be checked.

    Returns:
        Tuple[Optional[list], Optional[bool], tuple]: 3-tuple of

        * List of "edge info" lists. Each list represents a curved polygon
          and contains 3-tuples of edge index, start and end (see the
          output of :func:`ends_to_curve`).
        * "Contained" boolean. If not :data:`None`, indicates
          that one of the surfaces is contained in the other.
        * The nodes of three edges of the first surface being intersected
          followed by the nodes of the three edges of the second.
    """
    all_intersections = _algebraic_intersection.all_intersections
    return generic_intersect(
        nodes1, degree1, nodes2, degree2, verify, all_intersections)


# pylint: disable=invalid-name
if _surface_intersection_speedup is None:  # pragma: NO COVER
    newton_refine = _newton_refine
    locate_point = _locate_point
    geometric_intersect = _geometric_intersect
else:
    newton_refine = _surface_intersection_speedup.newton_refine
    locate_point = _surface_intersection_speedup.locate_point
    geometric_intersect = _surface_intersection_speedup.surface_intersections
# pylint: enable=invalid-name
