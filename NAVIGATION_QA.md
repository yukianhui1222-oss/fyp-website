# Navigation verification

Verified locally on 2026-09-26 using the production render functions with offline service fixtures.

## Fixes

- Give each page a stable Streamlit placeholder and hide inactive keyed page containers before rendering. This prevents outgoing page fragments from being reused visibly during navigation.
- Scope navigation styles to dedicated rail containers instead of horizontal blocks containing the logo. This prevents page content from acquiring rail dimensions.
- Make collapsed/expanded rail state explicit and prevent intermediate narrow wrappers from wrapping the expanded brand vertically.
- Update navigation and quiz question state in callbacks before rendering.
- Restore saved mixed-paper inputs on return, and original answers when reviewing an unsuccessful historical quiz.

## Coverage

| Area | Paths checked | Method |
| --- | --- | --- |
| Main navigation | Workspace, library, profile, leaderboard, return paths, rail expand/collapse | Browser + automated |
| Document entry | Documents menu, recent document, card grid, floating shelf preview/open | Browser + automated; shelf browser only |
| Results | Summary, translation, mind map, Quiz tabs; clear results | Browser + automated route checks |
| Quiz activities | Quiz, Flashcards, Study record; card flip/rating/navigation/shuffle | Browser + automated |
| Quiz session | Generate, submit, next/previous, question navigator, finish, review, exit, resume/discard, retry mistakes | Browser + automated; resume/discard/history automated |
| Mixed paper | Generate, save draft, return, restore draft, discard, grade, save marked paper | Browser + automated; saved-input retention verified by regression test |
| Utilities | Settings popover, study assistant popover, profile cancel/save | Browser + automated profile checks |
| Authentication display | Logout, login display, sign-up/sign-in form switching | Browser + automated logout |

Browser checks included navigation during a simulated document-fetch delay and immediate expanded/collapsed rail rendering. Page content retained normal width without the previous page's outlines.

## Repeatable checks

```powershell
python -X utf8 -m unittest test_navigation test_subject_library -q
python -X utf8 ui_smoke_test.py
python -m streamlit run navigation_preview.py --server.port 8767
```

Results: 18 unittest tests passed; 9 smoke checks passed. The preview uses synthetic data and mock services and is not the production entry point. Tests restore mocked service methods after each case.

## Limits

These checks do not verify the deployed site, real authentication, cloud persistence, or live AI responses. No real user records were changed. The Python 3.9 environment emits dependency compatibility warnings (including an importlib.metadata packages_distributions message); these did not fail the listed tests.
