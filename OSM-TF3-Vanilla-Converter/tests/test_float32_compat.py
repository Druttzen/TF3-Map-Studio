"""Pure-Lua native-float rounding must work without string.pack/unpack."""
from pathlib import Path
import math
import random
import struct
import unittest

from lupa import LuaRuntime


CONTENT = Path(__file__).resolve().parents[1] / 'mod/tf3_osm_importer_mod/content/osm'


def native_float(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


class Float32CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        # TF3's Lua runtime does not provide these Lua 5.3+ helpers.
        self.lua.execute('string.pack=nil; string.unpack=nil')
        self.controls = self.lua.execute((CONTENT/'controls.lua').read_text(encoding='utf-8'))

    def assert_native(self, value):
        actual = self.controls.float32(value)
        expected = native_float(value)
        # Compare encoded values to include the sign of zero and exact ties.
        self.assertEqual(struct.pack('<f', actual), struct.pack('<f', expected),
                         f'{value!r}: Lua={actual!r}, IEEE754={expected!r}')

    def test_zero_small_and_large_finite_values(self):
        values = (0.0, -0.0, 1.0, -1.0, 1e-45, -1e-45,
                  1e-40, -1e-40, 3.4e38, -3.4e38,
                  3.4028234663852886e38, -3.4028234663852886e38)
        for value in values:
            with self.subTest(value=value):
                self.assert_native(value)

    def test_round_to_nearest_ties_to_even_at_exponent_boundaries(self):
        values = []
        for exponent in (-126, -100, -24, -1, 0, 1, 13, 23, 100, 127):
            base = math.ldexp(1.0, exponent)
            spacing = math.ldexp(1.0, exponent-23)
            # An even lower significand rounds down; an odd one rounds up.
            for offset in (0.5, 1.5, 2.5, 3.5):
                midpoint = base+spacing*offset
                values.extend((midpoint, math.nextafter(midpoint, -math.inf),
                               math.nextafter(midpoint, math.inf)))
            values.extend((base, math.nextafter(base, 0.0),
                           math.nextafter(base, math.inf)))
        for value in values:
            for sign in (-1, 1):
                with self.subTest(value=sign*value):
                    self.assert_native(sign*value)

    def test_subnormal_and_normal_transition(self):
        unit = math.ldexp(1.0, -149)
        minimum_normal = math.ldexp(1.0, -126)
        values = (unit/4, unit/2, unit, 1.5*unit, 2.5*unit, 3.5*unit,
                  minimum_normal-unit, minimum_normal-unit/2,
                  minimum_normal, minimum_normal+unit/2)
        for value in values:
            for sign in (-1, 1):
                with self.subTest(value=sign*value):
                    self.assert_native(sign*value)

    def test_huge_map_coordinates_and_collapsing_triangle(self):
        for base in (8821.0, 10000.0, 10240.0):
            for delta in (0.0, 0.000001, 0.0001, 0.00048828125,
                          0.0009765625, 0.001, 0.01):
                for sign in (-1, 1):
                    with self.subTest(value=sign*(base+delta)):
                        self.assert_native(sign*(base+delta))
        face = self.lua.table_from([
            self.lua.table_from([10000.0, 10000.0]),
            self.lua.table_from([10000.0001, 10000.0]),
            self.lua.table_from([10000.0, 10000.0001]),
        ])
        result = self.controls.groundFace(face, None)
        self.assertIsInstance(result, tuple)
        self.assertIsNone(result[0])
        self.assertIn('collapses', result[1])

    def test_deterministic_random_finite_float32_range(self):
        rng = random.Random(172300)
        values = [rng.uniform(-10240.0, 10240.0) for _ in range(2000)]
        for _ in range(2000):
            exponent = rng.randrange(-149, 127)
            value = math.ldexp(rng.uniform(1.0, 2.0), exponent)
            values.append(value if rng.randrange(2) else -value)
        for value in values:
            self.assert_native(value)


if __name__ == '__main__':
    unittest.main()
