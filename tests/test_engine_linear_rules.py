import unittest
from datetime import date
from unittest.mock import patch

import engine


class LengthParsingTests(unittest.TestCase):
    def test_accepts_inventor_length_variants(self):
        self.assertEqual(engine.extract_length_mm("TUBO L-100,0 mm"), 100.0)
        self.assertEqual(engine.extract_length_mm("TUBO L=125"), 125.0)
        self.assertEqual(engine.extract_length_mm("TUBO LONGITUD: 25 cm"), 250.0)
        self.assertEqual(engine.extract_length_mm("TUBO L: 2.5 m"), 2500.0)

    def test_legacy_round_fallback_is_restricted_to_round_stock(self):
        desc = 'REDONDO NYLON-6/6 Ø3,5 X 60'
        self.assertEqual(engine.extract_length_mm(desc, 'REDONDO PLASTICO NYLON'), 60.0)
        self.assertIsNone(engine.extract_length_mm(desc, 'TUBERIA RECTANGULAR'))


class RuleTests(unittest.TestCase):
    def test_rule_inference_requires_meter_unit(self):
        self.assertEqual(engine.infer_rule_from_name('PERFIL A/C IPE 200', 'M'), '1')
        self.assertEqual(engine.infer_rule_from_name('REDONDO A/C Ø2', 'M'), '2')
        self.assertEqual(engine.infer_rule_from_name('TUBERIA INOX Ø4', 'M'), '8')
        self.assertIsNone(engine.infer_rule_from_name('CURVA TUBO INOX', 'Ud'))

    def test_tube_uses_length_plus_ten_mm_per_piece(self):
        master = {'NOMBRE': 'TUBERIA INOX Ø4', 'U': 'M', 'REGLA': '8'}
        result = engine.rule_usage(master, 'TUBERIA INOX Ø4 L-100,0 mm', 3)
        self.assertEqual(result['REGLA'], '8')
        self.assertAlmostEqual(result['USO'], 0.33)

    def test_round_uses_length_plus_five_mm_and_returns_meters(self):
        master = {'NOMBRE': 'REDONDO A/C Ø2', 'U': 'M', 'REGLA': '2'}
        result = engine.rule_usage(master, 'REDONDO A/C Ø2 L=125', 4)
        self.assertAlmostEqual(result['USO'], 0.52)

    def test_incompatible_linear_rule_does_not_erase_unit_quantity(self):
        master = {'NOMBRE': 'ABRAZADERA', 'U': 'Ud', 'REGLA': '1'}
        result = engine.rule_usage(master, 'ABRAZADERA', 4)
        self.assertEqual(result['REGLA'], 'NO')
        self.assertEqual(result['USO'], 4)
        self.assertIn('IGNORADA', result['ADVERTENCIA'])

    @patch('engine.config_map', return_value={'DIAS_PRODUCCION': 8})
    @patch('engine.load_master')
    def test_sheet_equivalent_is_rounded_only_once(self, load_master, _config):
        master = {
            '1010010002': {
                'CODIGO': '1010010002',
                'NOMBRE': 'LAMINA A/C ESP 3/8" 4FT X 8FT',
                'U': 'Ud', 'REGLA': '4', 'TIPO': 'PRODUCCION', 'NOTA': 'NO',
            }
        }
        load_master.return_value = (list(master.values()), master, engine.FIXED_RULES)
        lm = [{
            'CODIGO': '1010010002', 'NOMBRE': master['1010010002']['NOMBRE'],
            'UD': 'Ud', 'PENDIENTE': 6.720771, 'REGLA': '4', 'NOTA REGLA': '',
        }]
        result = engine.rq_proposal(lm, date(2026, 9, 10))
        self.assertEqual(result[0]['CANTIDAD'], 7)


if __name__ == '__main__':
    unittest.main()
