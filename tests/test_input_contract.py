"""核对文件交接格式。"""
import unittest
from pathlib import Path

from inspect_inputs import describe


class ImportContractTest(unittest.TestCase):
    def test_delivered_tables(self):
        tables = describe(Path("data"))
        self.assertEqual({table["文件"] for table in tables}, EXPECTED)
        for table in tables:
            with self.subTest(table=table["文件"]):
                self.assertGreater(table["记录数"], 0)


EXPECTED = {'appointments.csv', 'corrections.csv', 'invitations.csv', 'items.csv', 'responses.csv', 'rounds.csv'}
