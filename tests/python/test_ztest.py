"""What Zephyr's test framework printed on a console, read as a report."""

import pytest

from socpuppet import ztest


class TestWhenAConsoleEndsWithTheVerdictThatNothingFailed:
    def test_the_report_says_the_tests_passed(self):
        report = ztest.parse("spam\nPROJECT EXECUTION SUCCESSFUL\n")

        assert report.passed

    def test_the_verdict_is_the_word_successful(self):
        report = ztest.parse("spam\nPROJECT EXECUTION SUCCESSFUL\n")

        assert report.verdict == "SUCCESSFUL"


class TestWhenAConsoleEndsWithTheVerdictThatSomethingFailed:
    def test_the_report_says_the_tests_did_not_pass(self):
        report = ztest.parse("spam\nPROJECT EXECUTION FAILED\n")

        assert not report.passed

    def test_the_verdict_is_the_word_failed(self):
        report = ztest.parse("spam\nPROJECT EXECUTION FAILED\n")

        assert report.verdict == "FAILED"


class TestWhenAConsoleHasNoVerdict:
    """A run that was stopped, or an image with no test framework in it."""

    def test_the_report_has_no_verdict(self):
        report = ztest.parse("*** Booting Zephyr OS ***\nLovely spam!\n")

        assert report.verdict is None

    def test_the_report_does_not_say_the_tests_passed(self):
        report = ztest.parse("*** Booting Zephyr OS ***\nLovely spam!\n")

        assert not report.passed


class TestWhenAConsoleHasNoCaseInIt:
    """Firmware that stopped before its first test ended, most often."""

    def test_asking_for_a_case_says_that_there_are_none(self):
        report = ztest.parse("*** Booting Zephyr OS ***\n")

        with pytest.raises(KeyError, match="none at all"):
            report.case("spam.test_eggs")


#: What ztest prints of one suite with a case of each kind, as Zephyr
#: 4.4.2 printed it on a socpuppet board. The lines of the summary begin
#: with a space, and so do the lines that end a case.
ONE_SUITE = """\
*** Booting Zephyr OS build v4.4.2 ***
Running TESTSUITE spam
===================================================================
START - test_eggs
 PASS - test_eggs in 0.003 seconds
===================================================================
START - test_bacon
 SKIP - test_bacon in 0.001 seconds
===================================================================
START - test_sausage

    Assertion failed at WEST_TOPDIR/spam/src/main.c:42: spam_test_sausage: (sausage == spam is false)

 FAIL - test_sausage in 0.125 seconds
===================================================================
TESTSUITE spam failed.

------ TESTSUITE SUMMARY START ------

SUITE FAIL -  33.33% [spam]: pass = 1, fail = 1, skip = 1, total = 3 duration = 0.129 seconds
 - PASS - [spam.test_eggs] duration = 0.003 seconds
 - SKIP - [spam.test_bacon] duration = 0.001 seconds
 - FAIL - [spam.test_sausage] duration = 0.125 seconds

------ TESTSUITE SUMMARY END ------

===================================================================
PROJECT EXECUTION FAILED
"""


class TestWhenASuiteRanToItsSummary:
    def test_a_case_is_found_by_its_suite_and_its_name(self):
        report = ztest.parse(ONE_SUITE)

        found = report.case("spam.test_eggs")
        assert (found.suite, found.name) == ("spam", "test_eggs")

    def test_a_case_that_passed_says_so(self):
        report = ztest.parse(ONE_SUITE)

        assert report.case("spam.test_eggs").result == "PASS"

    def test_a_case_has_the_seconds_ztest_measured(self):
        report = ztest.parse(ONE_SUITE)

        assert report.case("spam.test_sausage").seconds == 0.125

    def test_a_case_printed_where_it_ended_and_again_in_the_summary_is_in_the_report_once(
        self,
    ):
        report = ztest.parse(ONE_SUITE)

        assert len(report.cases) == 3

    def test_the_cases_are_in_the_order_they_ran(self):
        report = ztest.parse(ONE_SUITE)

        assert [case.name for case in report.cases] == [
            "test_eggs",
            "test_bacon",
            "test_sausage",
        ]

    def test_a_case_that_failed_and_one_that_skipped_itself_say_so(self):
        report = ztest.parse(ONE_SUITE)

        assert (
            report.case("spam.test_sausage").result,
            report.case("spam.test_bacon").result,
        ) == ("FAIL", "SKIP")

    def test_asking_for_a_case_there_is_not_names_the_cases_there_are(self):
        report = ztest.parse(ONE_SUITE)

        with pytest.raises(KeyError) as refused:
            report.case("spam.test_lobster_thermidor")

        for case in ("spam.test_eggs", "spam.test_bacon", "spam.test_sausage"):
            assert case in str(refused.value)


#: A run that stopped in the middle of its second case: ztest prints its
#: summary only when every suite is over.
STOPPED_HALF_WAY = """\
Running TESTSUITE spam
===================================================================
START - test_eggs
 PASS - test_eggs in 0.003 seconds
===================================================================
START - test_bacon
"""


class TestWhenARunStoppedBeforeItsSummary:
    def test_a_case_that_had_ended_is_in_the_report(self):
        report = ztest.parse(STOPPED_HALF_WAY)

        assert report.case("spam.test_eggs") == ztest.Case(
            suite="spam", name="test_eggs", result="PASS", seconds=0.003
        )

    def test_the_case_it_stopped_in_is_not(self):
        report = ztest.parse(STOPPED_HALF_WAY)

        assert [case.name for case in report.cases] == ["test_eggs"]


#: 🎓 A test of a watchdog lets the watchdog reset its CPU, and carries on
#: from what it left in memory when the suite starts again. So one suite
#: begins three times here and ends once.
RESET_TWICE = """\
rom: zephyr: 27136 bytes to 0x20000000, jumping to 0x20000000
Running TESTSUITE spam
===================================================================
START - test_eggs
Waiting to restart MCU
rom: zephyr: 27136 bytes to 0x20000000, jumping to 0x20000000
Running TESTSUITE spam
===================================================================
START - test_eggs
Waiting to restart MCU
rom: zephyr: 27136 bytes to 0x20000000, jumping to 0x20000000
Running TESTSUITE spam
===================================================================
START - test_eggs
 PASS - test_eggs in 0.004 seconds
===================================================================
TESTSUITE spam succeeded
"""


class TestWhenASuiteBeginsAgainAfterEachOfTwoResets:
    def test_the_report_says_the_suite_started_three_times(self):
        report = ztest.parse(RESET_TWICE)

        assert report.suite("spam").starts == 3

    def test_the_suite_has_its_case_once(self):
        report = ztest.parse(RESET_TWICE)

        assert [case.name for case in report.suite("spam").cases] == [
            "test_eggs"
        ]


TWO_SUITES = """\
Running TESTSUITE spam
===================================================================
START - test_eggs
 PASS - test_eggs in 0.003 seconds
===================================================================
TESTSUITE spam succeeded
Running TESTSUITE bacon
===================================================================
START - test_eggs
 SKIP - test_eggs in 0.001 seconds
===================================================================
TESTSUITE bacon succeeded
"""


class TestWhenTwoSuitesEachHaveACaseOfTheSameName:
    def test_each_suite_has_its_own(self):
        report = ztest.parse(TWO_SUITES)

        assert (
            report.case("spam.test_eggs").result,
            report.case("bacon.test_eggs").result,
        ) == ("PASS", "SKIP")

    def test_the_suites_are_in_the_order_they_ran(self):
        report = ztest.parse(TWO_SUITES)

        assert [suite.name for suite in report.suites] == ["spam", "bacon"]

    def test_asking_for_a_suite_there_is_not_names_the_suites_there_are(self):
        report = ztest.parse(TWO_SUITES)

        with pytest.raises(KeyError) as refused:
            report.suite("lobster")

        assert "spam" in str(refused.value)
        assert "bacon" in str(refused.value)


class TestTheVerdictOfOneLineOfAConsole:
    """For what watches a console as it is printed, and stops at the verdict."""

    def test_the_line_ztest_ends_a_run_with_has_one(self):
        assert ztest.verdict_of("PROJECT EXECUTION FAILED") == "FAILED"

    def test_any_other_line_has_none(self):
        assert ztest.verdict_of("TESTSUITE spam failed.") is None


#: 🎓 A suite can say it is not to be run, and ztest then never begins it.
#: Its cases are in the summary all the same, each as skipped.
ONE_SUITE_RAN_AND_ONE_WAS_LEFT_OUT = """\
Running TESTSUITE spam
===================================================================
START - test_eggs
 PASS - test_eggs in 0.003 seconds
===================================================================
TESTSUITE spam succeeded

------ TESTSUITE SUMMARY START ------

SUITE PASS - 100.00% [spam]: pass = 1, fail = 0, skip = 0, total = 1 duration = 0.003 seconds
 - PASS - [spam.test_eggs] duration = 0.003 seconds

SUITE SKIP -   0.00% [bacon]: pass = 0, fail = 0, skip = 1, total = 1 duration = 0.000 seconds
 - SKIP - [bacon.test_ham] duration = 0.000 seconds

------ TESTSUITE SUMMARY END ------

===================================================================
PROJECT EXECUTION SUCCESSFUL
"""


class TestWhenASuiteWasLeftOutAndIsOnlyInTheSummary:
    def test_its_case_is_in_the_report_as_skipped(self):
        report = ztest.parse(ONE_SUITE_RAN_AND_ONE_WAS_LEFT_OUT)

        assert report.case("bacon.test_ham").result == "SKIP"

    def test_the_report_says_the_suite_never_started(self):
        report = ztest.parse(ONE_SUITE_RAN_AND_ONE_WAS_LEFT_OUT)

        assert report.suite("bacon").starts == 0
