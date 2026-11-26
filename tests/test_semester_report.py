import unittest

from atlas.semester_report import build_semester_report


def month(key, result, goals_for, goals_against, *, player_rating=None, partial=False, export=False):
    return {
        "month": key, "partial": partial, "pointsLeague": 3 if result == "V" else 1 if result == "E" else 0,
        "goalsFor": goals_for, "goalsAgainst": goals_against, "exports": 1 if export else 0,
        "matches": [{"result": result, "exportId": 9 if export else None}],
        "players": [{"playerEaId": 7, "name": "Player", "position": "ST", "minutes": 90,
                     "matchesWithRating": 1 if player_rating is not None else 0,
                     "averageRating": player_rating, "detailedMatches": 1 if export else 0}],
    }


class SemesterReportTests(unittest.TestCase):
    def setUp(self):
        self.report = {
            "careerId": 1, "seasonIndex": 2, "snapshotId": 8, "snapshotCareerDate": "2026-02-28",
            "teamEaId": 10, "teamName": "Club",
            "months": [
                month("2025-08", "V", 2, 0, player_rating=7.0, export=True),
                month("2025-12", "E", 1, 1, player_rating=8.0),
                month("2026-01", "D", 0, 2, player_rating=None, partial=True),
                month("2026-02", "V", 3, 1, player_rating=6.0, export=True),
            ],
        }

    def test_jul_to_dec_keeps_the_period_and_excludes_other_months(self):
        result = build_semester_report(self.report, 2)

        self.assertEqual(result["periodLabel"], "Jul-Dec")
        self.assertEqual(result["includedMonths"], ["2025-08", "2025-12"])
        self.assertEqual(result["excludedMonths"], ["2026-01", "2026-02"])
        self.assertEqual(result["metrics"], {
            "fixtures": 2, "resultCoverage": 2, "wins": 1, "draws": 1, "losses": 0,
            "goalsFor": 3, "goalsAgainst": 1, "pointsLeague": 4, "detailedExports": 1,
        })
        self.assertEqual(result["players"][0]["averageRating"], 7.5)

    def test_missing_rating_is_not_zero_and_partial_month_is_disclosed(self):
        result = build_semester_report(self.report, 1)

        self.assertEqual(result["includedMonths"], ["2026-01", "2026-02"])
        self.assertEqual(result["coverage"]["partialMonths"], ["2026-01"])
        self.assertEqual(result["players"][0]["averageRating"], 6.0)
        self.assertEqual(result["players"][0]["matchesWithRating"], 1)

    def test_rejects_invalid_semester(self):
        with self.assertRaisesRegex(ValueError, "Semester"):
            build_semester_report(self.report, 3)


if __name__ == "__main__":
    unittest.main()
