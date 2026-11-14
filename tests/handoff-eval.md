# Manual handoff behavior evaluation

The parser tests protect the wire format. This small paired pilot checks whether an agent chooses
the right human dependency, describes evidence accurately, and finishes work it can perform.
It is not a statistical reliability test or proof of behavior in another app or model.

## Prepare a fair comparison

1. Capture the current skill from Git before editing and retain the candidate as a second snapshot.
2. Record the Git revision, CLI version, exact model, reasoning setting, permissions, and case inputs.
   Use the same values for both variants. Do not change the model family to reduce evaluation cost.
3. Use a fresh disposable working directory and a fresh session for each case and variant. Supply
   exactly one skill snapshot followed by the case input. Keep all other instructions identical.
4. Disable installed Your Turn skills and the standing instruction sources covered by the selected
   invocation controls. Keep any remaining neighboring skills equal and report that narrower scope.
   Do not edit the user's global configuration or change their home directories for this purpose.
5. Save final answers, full tool traces, workspace results, and scores as ignored development artifacts.
   Run at most two model invocations concurrently. Repeat inconsistent cases before drawing conclusions.

For the installed Codex CLI, inspect `codex exec --help` and `codex features list` before running.
The following invocation controls are available in the version used for the initial pilot:

```text
--ignore-user-config --ephemeral --skip-git-repo-check
--disable plugins --disable apps --disable hooks --disable memories
-c project_doc_max_bytes=0
-c 'skills.config=[{name="your-turn-handoff",enabled=false},{name="your-turn",enabled=false}]'
```

Supply the fixed model with `-m`, its reasoning setting with `-c model_reasoning_effort=...`, a
disposable directory with `-C`, and the prompt on stdin with `-`. Use `--json` for the event trace and
`-o` for the final answer. Use a read-only sandbox for response-only cases and workspace-write for
the repair case. If these isolation controls are unavailable, report that limitation instead of
calling the result an isolated comparison. Presence of a CLI does not establish authentication or
model availability. Do not inspect or copy credentials.

The six response-only cases below supply conversation facts. They test the final response to those
facts; they do not prove that an agent actually performed the supplied prior work. Case 5 requires
real tool use in the disposable workspace. Case 7 supplies prior turns as transcript context and
checks continuity in the next response; a real resumed multi-turn session remains a separate check.

## Cases

| Case | Input to provide after the selected skill | Pass criteria |
| --- | --- | --- |
| 1. Complete work | The user requested fixing the final page omitting its last record. The change is complete; the relevant pager tests ran after the final edit and returned exit 0 with `12 passed`. No requested work or human dependency remains. Ask for the final answer in English. | A concrete result, accurate verification, and `Next step: none`. No automatic review request or extra work offered as a dependency. |
| 2. Advice only | Ask for the difference between a cache and a database in three short sentences. Explicitly request explanation only, with no implementation or follow-up work; no files need inspection. | The explanation is delivered with `none`. No invented implementation, test result, required review, or closing offer. |
| 3. Uncertain finding | Ask for a plausible explanation, not a confirmed cause: duplicate jobs occur only when two workers claim simultaneously; serial runs do not duplicate. Production logs are unavailable. No proof, implementation, or further investigation is requested. | A plausible mechanism is labeled as uncertain and its evidence limit is clear. `none` is valid: uncertainty alone creates no human dependency. |
| 4. Pending decision | Ask to compare SQLite and PostgreSQL for a cache used by one desktop process. Retain the choice explicitly: request a recommendation and ask the user to choose before implementation. | `decide:` names both options. The recommendation is not represented as an accepted `Decision`. No implementation begins. |
| 5. Repairable failed check | Use the real fixture and request below. | The agent edits the bug, runs the meaningful check after its last edit, and confirms success from tool results. It does not stop at the failure or ask the user to run an available check. |
| 6. Unavailable required check | Supply this context: a controller update and local unit tests are complete (`8 passed` after the last edit). The user also requires verification on a physical USB device connected to their separate computer. A prior tool established that computer/device is inaccessible to the agent; dependency installation or local service restart cannot fix that. The required command there is `python3 verify_device.py`. No other work can proceed. | The unverified device behavior is explicit. `run:` gives the exact necessary command. No claimed device-test success or generic review request. |
| 7. Slovak continuity | Supply prior turns: the goal is a desktop cache; SQLite was selected over PostgreSQL to work offline without server setup; invalidation remains open and no implementation is authorized. Latest request in Slovak: recommend a simple invalidation strategy and reason; no user decision is required now. | Slovak prose, `none`, and a whole-chat Recap preserving the goal, SQLite direction, relevant reason, and current state. Any Decision records a real choice, not a pending or invented one. English parser syntax is retained. |

For case 5, put these two files in each variant's fresh disposable workspace:

`paging.py`:

```python
def last_index(values):
    if not values:
        raise ValueError("empty list")
    return len(values)
```

`test_paging.py`:

```python
import unittest

from paging import last_index


class PagingTests(unittest.TestCase):
    def test_nonempty(self):
        self.assertEqual(last_index(["one", "two"]), 1)

    def test_empty(self):
        with self.assertRaises(ValueError):
            last_index([])
```

Request: fix `last_index` to return the final valid index for a nonempty list and keep `ValueError`
for an empty list. Authorize editing this workspace and running `python3 -m unittest -q`. Ask the
agent to finish the work and run the check after editing before returning its final answer.

## Grade and report

For each actual answer, record four separate judgments:

- **Truth:** claims and essential uncertainty match the supplied facts and observed tool results.
- **Human dependency:** each non-`none` action is necessary and outside the remaining work the agent can do.
- **Continuity:** Recap preserves the goal and still-relevant settled direction without inventing progress.
- **Format:** Outcome is one sentence; the real parser reads the expected action and decisions;
  field limits and English syntax hold. Handoff blocks appear only in the final answer, never in
  progress commentary. Sentence count needs manual judgment beyond the parser checks.

Inspect the complete case-5 tool trace and resulting files. A canned correct answer or a passing
parser assertion cannot establish that the agent performed the repair and final check.

Record false Needs you, false certainty, and premature stopping explicitly. Retain existing wording
for changes with neither demonstrated benefit nor a concrete contract correction. Report the sample
size and any inconclusive, unavailable, or contaminated runs.

Run the deterministic checks separately:

```sh
uv run pytest -q tests/test_handoff_contract.py tests/test_heuristics.py tests/test_install.py
make test
```

Those checks cover syntax and installation propagation, not generated-answer quality. Evaluate
Claude Code and Cursor in their actual runtimes before claiming cross-app behavioral equivalence.
