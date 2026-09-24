"""Offline UI smoke checks. Run: python -X utf8 ui_smoke_test.py"""
from pathlib import Path
from streamlit.testing.v1 import AppTest
source = Path(__file__).with_name('app.py').read_text(encoding='utf-8')
source = source.replace('\npatch_streamlit_index_html()', '\n# Skip installed-package edits in tests')
source = source.replace('\npatch_streamlit_js_hotkeys()', '\n# Skip installed-package edits in tests')
source = source[:source.rindex('if __name__ == "__main__":')]
source += '''
initialize_models = lambda: True
fetch_saved_summaries = lambda *a, **kw: ([], None)
fetch_leaderboard = lambda *a, **kw: ([], None)
fetch_quiz_attempts = lambda *a, **kw: ([], None)
fetch_user_progression = lambda *a, **kw: ({}, None)
main()
'''
app = AppTest.from_string(source, default_timeout=25)
app.secrets['GEMINI_API_KEY'] = 'offline-test'
def check(name):
    app.run()
    assert not app.exception, [e.message for e in app.exception]
    print('PASS', name)
check('login')
app.session_state['user'] = {'uid':'ui-test', 'name':'Test User', 'email':'test@example.invalid', 'idToken':'test'}
app.session_state['user_profile'] = {'uid':'ui-test', 'name':'Test User', 'role':'Standard Account'}
check('home')
assert app.session_state['_rendered_page_route'] == 'home'
app.button(key='toggle_navigation').click()
check('expanded navigation')
assert app.session_state['nav_expanded'] is True
assert app.button(key='toggle_navigation').label == 'DocuMind'
app.button(key='toggle_navigation').click()
check('collapsed navigation')
assert app.session_state['nav_expanded'] is False
assert app.button(key='main_start_analysis_btn').disabled
assert app.button(key='main_clear_disabled_btn').disabled
for flag in ['edit_profile_active', 'leaderboard_active']:
    app.session_state[flag] = True
    check(flag)
    assert app.session_state['_rendered_page_route'] == {'edit_profile_active': 'profile', 'leaderboard_active': 'leaderboard'}[flag]
    app.session_state[flag] = False
app.session_state['quiz_data'] = [{'question':'Which is a document format?', 'options':['A. PDF','B. Blue'], 'correct_answer':'A. PDF', 'explanation':'PDF is a document format.'}]
app.session_state['quiz_mode_active'] = True
check('quiz')
app.session_state['quiz_mode_active'] = False
app.session_state['ocr_results'] = {'raw_text':'A short test document.', 'summary':'## Summary\nA short test document.', 'translation':'Test translation.', 'lang':'Chinese', 'filename':'test.pdf', 'time':1.0, 'mindmap_eng':'# Test\n## Document', 'mindmap_trans':'# Translation\n## Document', 'is_loaded_from_db':True}
check('results')
assert app.session_state['_rendered_page_route'] == 'results'
assert len(app.tabs) == 4
app.button(key='main_clear_results_btn').click()
check('clear results')
assert app.session_state['_rendered_page_route'] == 'home'
assert 'ocr_results' not in app.session_state
