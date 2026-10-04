---
name: test-design-review
description: Review tests for design quality against the test design guidelines. Runs in its own subagent.
argument-hint: [test files or paths]
context: fork
background: false
---

# Test Design Review

Review the tests named under "Tests to review" below, or if none are named, the test changes in the working tree at the end of this document. Read any untracked test files the status listing shows. Do not edit files; report only.

For each violation found, show the offending code and suggest a fix. Group by guideline and skip guidelines with no violations. If nothing violates any guideline, say so in one line; don't invent findings.

## Tests to review

$ARGUMENTS

## Guidelines

Tests are executable specifications: "in scenario X, Y happens".

### Name the scenario and the expected behavior

The scenario and the outcome both appear in the test name or its enclosing group (pytest class, gtest suite, Rust `mod`). "It works correctly", "handles errors", "validates input" specify nothing.

Bad:
```python
class TestScopeFailed:
    def test_returns_the_correct_value(self):
```

Good:
```python
class TestRerunningOnlyFailedTests:
    def test_when_status_is_passed_returns_passed(self):
```

```rust
mod when_a_particle_touches_a_grid_cell {
    #[test]
    fn the_cell_turns_the_particles_color() { ... }
}
```

### Test behavior, not implementation

Assert on the observable end result, never on the means: no `assert_called_once_with`, `EXPECT_CALL`, cache keys, current URL, or a specific internal field. Stub only what you must (external services) and let real code run. One pair covers the whole family:

Bad:
```python
def test_queues_the_task(mocker, task):
    worker_pool = mocker.patch("jobs.WorkerPool").return_value
    QueueUnqueuedTasksJob().perform()
    worker_pool.queue_task.assert_called_once_with(task)

def test_caches_the_result(test_suite_run):
    test_suite_run.duration()
    assert cache.get(f"test_suite_run/{test_suite_run.id}/duration") is not None
```

Good:
```python
def test_queues_the_task(task):
    QueueUnqueuedTasksJob().perform()
    assert TaskEvent.count(name="queued") == 1

def test_does_not_query_the_database_on_subsequent_calls(test_suite_run):
    test_suite_run.duration()
    with count_queries() as second_call:
        test_suite_run.duration()
    assert second_call.count == 0
```

The same applies to setup: drive state through the public path the code under test uses (`task.update(exit_code=0)`), not by poking the internal representation it derives from (`task.update(json_output=...)`). Parse helpers the way a user would (find the link by its text), not by regex over markup.

### Assert only what is essential

Drop assertions implied by others (a body check already fails on a bad status code), incidental details, and noise.

### Don't pick records by position

`[0]`, `[-1]`, `.first()`, `.last()` depend on ordering. Query for the record you mean, or assert on the change (`count == before + 1`).

### Keep one level of abstraction

A test that reads at the level of pages and buttons does not set env vars or patch permissions inline; that plumbing goes in a fixture or nowhere. Dense incidental mechanics (listeners, try/finally) go in a helper defined after the test, so the test shows only its essence. Define fixtures before their users, or hard-code the value:

```python
def test_when_task_id_is_a_non_empty_string_returns_task_prefixed_id(self):
    worker = Worker(Mock(task_id="123"))
    assert worker.docker_compose_project_name == "task-123"
```

### Never reach into private state

No `obj._helper()`, `setattr(obj, "_state", ...)`, `obj.__dict__`, `mocker.patch.object(obj, "_private")`, `#define private public`, `FRIEND_TEST`, or friend classes. If a private method needs a test, make it public, or treat the urge as a design smell and suggest a specific refactor.

### No speculative values

A `timeout=3000`, `time.sleep(3)`, or retry count needs a reason; if it was cargo culted, cut it.

### Hard-code what the spec says, look up what the environment says

Inputs that are part of the specification are hard-coded (`"123"` in, `"task-123"` out). Values the test does not own are not: anything copied from generated code, a config file, a schema, or the environment (a register address from a generated header, a port number from a config file, an ID from a seeded database). Copying such a value couples the test to something that changes for unrelated reasons. Read it from the same source the code under test uses, or shape the assertion so the exact value does not matter.

Bad:
```python
def test_when_a_byte_is_written_to_the_data_register_the_uart_holds_it(bus, uart):
    bus.write(0x4000_1000, 0x41)  # copied from the generated memory map
    assert uart.data_register == 0x41
```

Good:
```python
def test_when_a_byte_is_written_to_the_data_register_the_uart_holds_it(bus, uart):
    bus.write(memory_map.UART0.data, 0x41)
    assert uart.data_register == 0x41
```

## Working tree

!`git status --porcelain`

## Diff

!`git diff HEAD`
