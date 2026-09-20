"""Offline tests for folder writes, paper validation and full submission flow."""
import copy
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
import subject_library as lib

QUESTIONS = [
    {'id': 'q1', 'type': 'mcq', 'question': 'Choose A', 'options': ['A', 'B', 'C', 'D'], 'answer': 'A', 'sources': ['d1'], 'marks': 2},
    {'id': 'q2', 'type': 'short', 'question': 'Explain B', 'answer': 'B explained', 'rubric': 'Explanation: 10 marks', 'sources': ['d2'], 'marks': 10},
]

class LibraryTests(unittest.TestCase):
    def test_move_is_atomic_and_preserves_content(self):
        with patch.object(lib, 'request_json') as request:
            lib.move_documents('u', 'token', ['d1', 'd2'], 'f')
            writes = request.call_args.args[3]['writes']
            self.assertEqual(len(writes), 2)
            self.assertEqual(writes[0]['updateMask']['fieldPaths'], ['folder_id'])
            self.assertEqual(writes[0]['currentDocument'], {'exists': True})
            self.assertEqual(writes[0]['update']['fields'], {'folder_id': {'stringValue': 'f'}})

    def test_pagination(self):
        with patch.object(lib, 'request_json', side_effect=[{'documents': [{'name': 'x/d1', 'fields': {}}], 'nextPageToken': 'a+b'}, {'documents': [{'name': 'x/d2', 'fields': {}}]}]) as request:
            self.assertEqual(len(lib.list_saved_documents('u', 't')), 2)
            self.assertIn('pageToken=a%2Bb', request.call_args.args[0])

    def test_paper_rejects_missing_sources_and_invalid_options(self):
        self.assertEqual(len(lib.validate_paper({'questions': copy.deepcopy(QUESTIONS)}, {'d1','d2'}, 1, 1)), 2)
        invalid = copy.deepcopy(QUESTIONS)
        invalid[1]['sources'] = ['d1']
        with self.assertRaises(ValueError):
            lib.validate_paper({'questions': invalid}, {'d1','d2'}, 1, 1)
        invalid = copy.deepcopy(QUESTIONS)
        invalid[0]['answer'] = 'E'
        with self.assertRaises(ValueError):
            lib.validate_paper({'questions': invalid}, {'d1','d2'}, 1, 1)

    def test_generation_repairs_wrong_count(self):
        import json
        from types import SimpleNamespace
        with patch('summarizer._get_model_name', return_value='test'), patch('summarizer.genai.GenerativeModel'), patch('summarizer._generate_with_retry', side_effect=[SimpleNamespace(text=json.dumps({'questions': QUESTIONS[:1]})), SimpleNamespace(text=json.dumps({'questions': QUESTIONS}))]) as generate:
            result = lib.generate_paper([{'id':'d1','summary':'A'}, {'id':'d2','summary':'B'}], 'key', 'English', 1, 1)
            self.assertEqual(len(result), 2)
            self.assertEqual(generate.call_count, 2)
            self.assertIn('EXACTLY 2', generate.call_args.args[1])

    def test_generation_stops_after_three_invalid_responses(self):
        from types import SimpleNamespace
        with patch('summarizer._get_model_name', return_value='test'), patch('summarizer.genai.GenerativeModel'), patch('summarizer._generate_with_retry', return_value=SimpleNamespace(text='{"questions": []}')) as generate:
            with self.assertRaises(ValueError):
                lib.generate_paper([{'id':'d1','summary':'A'}], 'key', 'English', 1, 1)
            self.assertEqual(generate.call_count, 3)

    def test_blank_answers_score_zero_without_ai(self):
        self.assertEqual(sum(x['score'] for x in lib.grade_paper(QUESTIONS, {}, '').values()), 0)

    def test_ui_generate_submit_retry_and_grade(self):
        source = '''
import streamlit as st
from subject_library_ui import render_library
st.session_state.user = {'uid':'test', 'idToken':'token'}
render_library('test-key')
'''
        docs = [{'id':'d1','title':'Lecture 1','summary':'A','folder_id':'f'}, {'id':'d2','title':'Lecture 2','summary':'B','folder_id':'f'}]
        with patch.object(lib, 'list_folders', return_value=[{'id':'f','name':'Physics'}]), patch.object(lib, 'list_saved_documents', return_value=docs), patch.object(lib, 'generate_paper', return_value=copy.deepcopy(QUESTIONS)), patch.object(lib, 'grade_paper', side_effect=[ValueError('temporary'), {'q1':{'score':2,'feedback':'Correct'},'q2':{'score':8,'feedback':'More detail needed'}}]):
            app = AppTest.from_string(source).run()
            app.selectbox(key='folder_browse_test').select('f').run()
            next(b for b in app.button if b.label == 'Generate mixed paper').click().run()
            self.assertFalse(app.exception)
            app.radio[0].set_value('A')
            app.text_area[0].set_value('My explanation')
            next(b for b in app.button if b.label == 'Submit paper for marking').click().run()
            self.assertEqual(app.text_area[0].value, 'My explanation')
            self.assertIsNone(app.session_state['subject_paper_test']['grades'])
            next(b for b in app.button if b.label == 'Submit paper for marking').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state['subject_paper_test']['grades']['q2']['score'], 8)
            self.assertTrue(any('10 / 12' in item.value for item in app.success))

if __name__ == '__main__':
    unittest.main()
