"""Reference-map navigation must not reinterpret display data or lose date-line routes."""
import unittest
from argus.map_view import coordinates, find_ports, geographic_extent, route_name


class MapViewTests(unittest.TestCase):
    ports = [[1, 'São Pedro', -23, -46, 'BR'], [2, 'Dublin', 53, -6, 'IE'],
             [3, 'Dublin Bay', 53.1, -6.1, 'IE'], [4, 'Tokyo', 35, 139, 'JP']]

    def test_search_combines_country_visible_set_and_accent_insensitive_tokens(self):
        self.assertEqual(find_ports(self.ports, 'sao BR'), [0])
        self.assertEqual(find_ports(self.ports, 'dublin', 'IE', {2}), [2])
        self.assertEqual(find_ports(self.ports, '4'), [3])
        self.assertEqual(find_ports(self.ports, 'unknown'), [])

    def test_coordinate_hemispheres(self):
        self.assertEqual(coordinates(-23, 139), '23.0000°S, 139.0000°E')

    def test_missing_system_names_remain_explicit_and_distinguishable(self):
        self.assertEqual(route_name({'name': 'Unnamed cable'}, 9), 'Unnamed route 010')
        self.assertEqual(route_name({'name': 'Topaz'}, 9), 'Topaz')

    def test_route_extent_wraps_date_line_instead_of_fitting_the_whole_world(self):
        center, lat_span, lon_span = geographic_extent([(20, 179), (30, -179)])
        self.assertEqual(center, (25, -180))
        self.assertEqual((lat_span, lon_span), (10, 2))
        self.assertEqual(geographic_extent([(53, -6)])[1:], (0, 0))
