"""Exercise real navigation buttons with isolated offline service fixtures."""
import os
os.environ['NAV_TEST_DELAY'] = '0'
import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest

class NavigationTests(unittest.TestCase):
    def setUp(self):
        # The standalone browser fixture installs module-level offline services.
        # Restore them after each test so other suites exercise real functions.
        import subject_library
        import summarizer
        names = {
            subject_library: ['list_folders', 'list_saved_documents', 'list_papers', 'generate_paper', 'grade_paper', 'save_paper'],
            summarizer: ['generate_quiz', 'generate_flashcards'],
        }
        self.original_services = {(module, name): getattr(module, name) for module, fields in names.items() for name in fields}
        self.addCleanup(self.restore_services)
        self.app = AppTest.from_file(str(Path(__file__).with_name('navigation_preview.py')), default_timeout=25)
        self.app.secrets['GEMINI_API_KEY'] = 'offline-navigation-test'
        self.app.run()
        self.assertRoute('home')

    def restore_services(self):
        for (module, name), value in self.original_services.items():
            setattr(module, name, value)

    def assertRoute(self, route):
        self.assertFalse(self.app.exception, [e.message for e in self.app.exception])
        # Incorrect-answer feedback is intentional, not an application failure.
        unexpected_errors = [e.value for e in self.app.error
                             if not (route == 'quiz' and e.value.startswith('**Incorrect.**'))]
        self.assertFalse(unexpected_errors, unexpected_errors)
        self.assertEqual(self.app.session_state['_rendered_page_route'], route)
        # A route marker is emitted before rendering the page, excluding all old views.
        html = '\n'.join(e.proto.body for e in self.app.get('html'))
        self.assertIn(f':not(.st-key-page_view_{route})', html)

    def click(self, key, route=None):
        self.app.button(key=key).click().run()
        self.assertFalse(self.app.exception, [e.message for e in self.app.exception])
        if route:
            self.assertRoute(route)

    def open_results(self):
        self.click('resume_saved_0', 'results')

    def test_home_library_profile_leaderboard_round_trips(self):
        for _ in range(2):
            self.click('open_subject_library', 'library')
            self.click('library_back', 'home')
            self.click('nav_edit_profile_btn', 'profile')
            self.click('profile_cancel_btn', 'home')
            self.click('nav_leaderboard_btn', 'leaderboard')
            self.click('lbl_back_home_btn', 'home')
            self.click('toggle_navigation', 'home')
            self.click('toggle_navigation', 'home')

    def test_results_round_trips_and_document_entries(self):
        self.click('load_doc_navigation-doc', 'results')
        for entry, back, route in [('open_subject_library', 'library_back', 'library'), ('nav_edit_profile_btn', 'profile_cancel_btn', 'profile'), ('nav_leaderboard_btn', 'lbl_back_home_btn', 'leaderboard')]:
            self.click(entry, route)
            self.click(back, 'results')
        self.click('open_subject_library', 'library')
        next(r for r in self.app.radio if r.label == 'Material view').set_value('Card grid').run()
        self.click('folder_open_navigation-doc', 'results')
        self.click('main_clear_results_btn', 'home')
        self.open_results()
        self.click('nav_edit_profile_btn', 'profile')
        self.click('profile_save_btn', 'results')

    def test_quiz_hub_flashcards_and_record(self):
        self.open_results()
        self.assertEqual([t.label for t in self.app.tabs], ['Summary', 'Chinese translation', 'Mind map', 'Quiz'])
        self.click('quiz_activity_Flashcards', 'results')
        self.click('generate_flashcards', 'results')
        before = self.app.button(key='knowledge_card_face').label
        self.click('knowledge_card_face', 'results')
        self.assertNotEqual(before, self.app.button(key='knowledge_card_face').label)
        for key in ['card_known', 'flashcard_next', 'flashcard_previous', 'flashcard_shuffle', 'quiz_activity_Study record', 'quiz_activity_Quiz']:
            self.click(key, 'results')
        self.assertTrue(self.app.button(key='generate_quiz_action_btn'))

    def test_quiz_answer_next_previous_navigator_review_exit(self):
        self.open_results()
        self.click('generate_quiz_action_btn', 'quiz')
        next(r for r in self.app.radio if r.label == 'Options').set_value(self.app.session_state['quiz_data'][0]['correct_answer']).run()
        self.click('submit_answer_action_btn', 'quiz')
        self.assertTrue(self.app.button(key='next_quiz_action_btn'))
        self.click('next_quiz_action_btn', 'quiz')
        self.assertTrue(any('What absorbs light?' in m.value for m in self.app.markdown))
        self.click('prev_quiz_action_btn', 'quiz')
        self.assertTrue(any('What do plants convert?' in m.value for m in self.app.markdown))
        self.click('nav_q_1', 'quiz')
        self.assertTrue(any('What absorbs light?' in m.value for m in self.app.markdown))
        next(r for r in self.app.radio if r.label == 'Options').set_value(self.app.session_state['quiz_data'][1]['correct_answer']).run()
        self.click('submit_answer_action_btn', 'quiz')
        self.click('finish_quiz_action_btn', 'quiz')
        self.click('review_final_btn', 'quiz')
        self.assertTrue(any('Review your answers' in e.proto.body for e in self.app.get('html')))
        self.click('next_quiz_action_btn', 'quiz')
        self.click('finish_quiz_action_btn', 'results')
        self.click('generate_quiz_action_btn', 'quiz')
        self.click('exit_quiz_action_btn', 'results')
        self.click('generate_quiz_action_btn', 'quiz')
        self.app.session_state['quiz_finished'] = True
        self.app.run()
        self.click('ret_doc_final_btn', 'results')

    def test_history_review_retry_and_resume(self):
        self.open_results()
        self.click('quiz_activity_Study record', 'results')
        self.click('rev_att_previous-attempt', 'quiz')
        self.assertEqual(self.app.session_state['user_ans_0'], 'Stone')
        self.click('exit_quiz_action_btn', 'results')
        self.click('ret_att_previous-attempt', 'quiz')
        self.assertTrue(self.app.session_state['is_retry'])
        self.click('exit_quiz_action_btn', 'results')
        self.click('quiz_activity_Quiz', 'results')
        self.click('generate_quiz_action_btn', 'quiz')
        self.app.session_state['quiz_mode_active'] = False
        self.app.run()
        self.click('resume_quiz_btn', 'quiz')
        self.app.session_state['quiz_mode_active'] = False
        self.app.run()
        self.click('discard_quiz_btn', 'results')
        self.assertFalse(self.app.session_state['quiz_data'])

    def test_mixed_paper_generate_save_return_restore_grade(self):
        self.click('open_subject_library', 'library')
        next(b for b in self.app.button if b.label == 'Generate mixed paper').click().run()
        self.assertRoute('library')
        paper = self.app.session_state['subject_paper_navigation-user']
        paper_id = paper['id']
        next(r for r in self.app.radio if r.label == 'Select one answer').set_value('Light')
        next(b for b in self.app.button if b.label == 'Save draft to account').click().run()
        self.click('library_back', 'home')
        self.click('open_subject_library', 'library')
        self.assertEqual(next(r for r in self.app.radio if r.label == 'Select one answer').value, 'Light')
        self.app.checkbox(key='discard_' + paper_id).check().run()
        next(b for b in self.app.button if b.label == 'Start new paper').click().run()
        self.click('load_saved_papers', 'library')
        self.click('restore_' + paper_id, 'library')
        self.assertEqual(next(r for r in self.app.radio if r.label == 'Select one answer').value, 'Light')
        next(b for b in self.app.button if b.label == 'Submit paper for marking').click().run()
        self.assertRoute('library')
        self.assertIsNotNone(self.app.session_state['subject_paper_navigation-user']['grades'])
        self.click('save_marked_paper', 'library')
        self.click('library_back', 'home')

    def test_logout(self):
        self.click('nav_logout_button', 'login')
        self.assertIsNone(self.app.session_state['user'])

    def test_home_subject_and_review_queue(self):
        self.click('home_subject_biology', 'library')
        self.assertEqual(self.app.selectbox(key='folder_browse_navigation-user').value, 'biology')
        self.click('library_back', 'home')
        self.assertEqual(self.app.metric[0].value, '2')
        self.open_results()
        self.click('quiz_activity_Flashcards', 'results')
        self.click('generate_flashcards', 'results')
        self.click('knowledge_card_face', 'results')
        self.click('card_again', 'results')
        self.click('main_clear_results_btn', 'home')
        self.assertEqual(self.app.metric[1].value, '1')
        next(c for c in self.app.checkbox if c.label == 'Show answer').check().run()
        next(b for b in self.app.button if b.label == 'Got it ✓').click().run()
        self.assertEqual(self.app.metric[1].value, '0')
        self.app.session_state['home_review_attempts_navigation-user'] = None
        self.app.run()
        self.assertEqual(self.app.metric[0].value, '—')
        self.click('home_refresh_review', 'home')
        self.assertEqual(self.app.metric[0].value, '2')

    def test_navigation_css_is_owned(self):
        for name in ['app.py', 'ui_theme.css']:
            source = Path(__file__).with_name(name).read_text(encoding='utf-8')
            self.assertNotIn('div[data-testid="stHorizontalBlock"]:has(.documind-nav-brand)', source)

if __name__ == '__main__':
    unittest.main()
