"""LOCAL ONLY browser regression fixture. No real account, AI or database writes.
Run: python -m streamlit run navigation_preview.py --server.port 8767
"""
from pathlib import Path
import os
import json
import copy
import time
import streamlit as st
os.environ['GEMINI_API_KEY'] = 'offline-navigation-test'
source = Path(__file__).with_name('app.py').read_text(encoding='utf-8')
source = source.replace('\npatch_streamlit_index_html()', '\n# disabled in fixture')
source = source.replace('\npatch_streamlit_js_hotkeys()', '\n# disabled in fixture')
source = source[:source.rindex('if __name__ == "__main__":')]
exec(compile(source, str(Path(__file__).resolve()), 'exec'), globals())
DOC = dict(id='navigation-doc', title='Navigation sample notes', filename='Navigation sample notes', language='Chinese', lang='Chinese', raw_text='Photosynthesis converts light to chemical energy.', summary='## Photosynthesis\nPlants convert light into chemical energy.\n\n## Chlorophyll\nChlorophyll absorbs light.', translation='## 光合作用\n植物将光能转化为化学能。', mindmap_eng='# Plants\n## Photosynthesis\n## Chlorophyll', mindmap_trans='# 植物\n## 光合作用', time=1.0, timestamp='2026-09-24T00:00:00Z', folder_id='', is_loaded_from_db=True)
QUESTIONS = [dict(question='What do plants convert?', options=['Light', 'Stone', 'Metal', 'Plastic'], correct_answer='Light', explanation='Plants use light energy.', topic='Plants'), dict(question='What absorbs light?', options=['Chlorophyll', 'Stone', 'Metal', 'Plastic'], correct_answer='Chlorophyll', explanation='Chlorophyll absorbs light.', topic='Plants')]
initialize_models = lambda: True
fetch_saved_summaries = lambda *a, **k: ([DOC.copy()], None)
fetch_leaderboard = lambda *a, **k: ([], None)
fetch_quiz_attempts = lambda *a, **k: ([dict(attempt_id='previous-attempt', date='2026-09-24T00:00:00Z', topic=DOC['title'], difficulty='Medium', score=1, total_questions=2, duration_seconds=60, answers=[dict(q, user_answer='Stone', is_correct=False) for q in copy.deepcopy(QUESTIONS)])], None)
fetch_user_progression = lambda *a, **k: ({}, None)
fetch_user_details = lambda *a, **k: ({'uid':'navigation-user','name':'Navigation Tester'}, None)
save_user_details = lambda *a, **k: (True, 'Saved locally')
save_quiz_attempt = lambda *a, **k: (True, 'local-attempt')
update_user_xp_level = lambda *a, **k: (True, {})
import summarizer
summarizer.generate_quiz = lambda *a, **k: (json.dumps(QUESTIONS), None)
summarizer.generate_flashcards = lambda *a, **k: (json.dumps(QUESTIONS), None)
import subject_library as library
library.list_folders = lambda *a, **k: [dict(id='biology', name='Biology')]
def slow_documents(*a, **k):
    time.sleep(float(os.environ.get('NAV_TEST_DELAY', '0.5')))
    return [DOC.copy()]
library.list_saved_documents = slow_documents
def preview_paper(docs, api_key, language, mcq_count=4, short_count=2, on_progress=None):
    result = []
    for index in range(mcq_count + short_count):
        kind = 'mcq' if index < mcq_count else 'short'
        result.append(dict(id=f'q{index+1}', type=kind, question=f'Practice question {index+1}: explain photosynthesis.', options=['Light', 'Stone', 'Metal', 'Plastic'], answer='Light', rubric='Identify light energy.', sources=[docs[0]['id']], marks=2 if kind == 'mcq' else 10))
    return result
library.generate_paper = preview_paper
library.grade_paper = lambda questions, answers, key: {q['id']: dict(score=q['marks'] if answers.get(q['id']) else 0, feedback='Offline test feedback') for q in questions}
def preview_save_paper(uid, token, paper):
    st.session_state['_preview_saved_paper'] = copy.deepcopy(paper)
library.save_paper = preview_save_paper
library.list_papers = lambda *a, **k: [dict(paper=copy.deepcopy(st.session_state['_preview_saved_paper']), updated_at='2026-09-24T00:00:00Z')] if '_preview_saved_paper' in st.session_state else []
if '_preview_initialized' not in st.session_state:
    st.session_state['_preview_initialized'] = True
    st.session_state['user'] = dict(uid='navigation-user', name='Navigation Tester', email='preview@example.invalid', idToken='offline')
    st.session_state['user_profile'] = dict(uid='navigation-user', name='Navigation Tester', role='Standard Account')
main()
