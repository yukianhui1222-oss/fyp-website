"""Subject shortcuts and review queues backed by existing study data."""
import streamlit as st
import subject_library as library
from navigation import navigate_to


def open_subject(folder_id):
    st.session_state['pending_subject_folder'] = folder_id
    navigate_to('library')


def mark_reviewed(deck_key, question):
    deck = st.session_state[deck_key]
    deck['again'] = [q for q in deck.get('again', []) if q != question]
    if question not in deck.setdefault('known', []):
        deck['known'].append(question)


def render_home_tools(uid, token, fetch_attempts):
    with st.container(key='home_subject_shortcuts'):
        st.html('<div class="home-section-heading"><span class="home-section-icon">▤</span><div><span class="home-section-kicker">SUBJECT SPACES</span><h3>Jump into a subject</h3></div></div>')
        try:
            folders = library.list_folders(uid, token) if uid and token else []
        except Exception:
            folders = None
            st.caption('Subjects could not be loaded. Open your library to retry.')
        if folders:
            columns = st.columns(min(len(folders), 4))
            for index, folder in enumerate(folders[:4]):
                with columns[index % 4]:
                    st.button('📁 ' + folder['name'], key=f'home_subject_{folder["id"]}', on_click=open_subject, args=(folder['id'],), use_container_width=True)
        elif folders is not None:
            st.caption('Keep lectures from the same course together. Create your first subject folder to get started.')
        st.button('All subjects & folders →', key='home_all_subjects', on_click=navigate_to, args=('library',))

    with st.container(key='home_review_queue'):
        st.html('<div class="home-section-heading"><span class="home-section-icon">↺</span><div><span class="home-section-kicker">A LITTLE PRACTICE</span><h3>Ready for another look?</h3></div></div>')
        owner = uid or 'guest'
        cache_key = f'home_review_attempts_{owner}'
        refresh = st.button('Refresh review list', key='home_refresh_review')
        if cache_key not in st.session_state or refresh:
            attempts, error = fetch_attempts(uid, token) if uid and token else (st.session_state.get('guest_quiz_attempts', []), None)
            st.session_state[cache_key] = None if error else attempts
        attempts = st.session_state.get(cache_key)
        mistakes = [(a, q) for a in (attempts or []) for q in a.get('answers', []) if q.get('is_correct') is False]
        cards = [(key, deck, card) for key, deck in st.session_state.items()
                 if key.startswith('knowledge_cards_v2_') and isinstance(deck, dict) and deck.get('owner') == owner
                 for card in deck.get('cards', []) if card['question'] in deck.get('again', [])]
        left, right = st.columns(2)
        with left:
            st.metric('Saved incorrect answers', len(mistakes) if attempts is not None else '—')
        with right:
            st.metric('Cards marked “Practice again”', len(cards))
        st.caption('Incorrect answers are from saved attempts. Flashcard reminders last for this session.')
        if attempts is None:
            st.caption('Quiz history could not be loaded. Refresh to try again.')
        if not mistakes and not cards and attempts is not None:
            st.caption('Nothing queued yet. Complete a quiz or mark a flashcard “Practice again”.')
        with st.expander('Review incorrect answers', expanded=False):
            for index, (attempt, question) in enumerate(mistakes):
                st.caption(str(attempt.get('topic', 'Quiz')))
                st.write(str(question.get('question', '')))
                if st.checkbox('Reveal answer', key=f'home_mistake_{index}'):
                    st.write(str(question.get('correct_answer', '')))
                    st.write(str(question.get('explanation', '')))
            if not mistakes:
                st.caption('No saved incorrect answers to show.' if attempts is not None else 'Refresh the review list to retry loading.')
        with st.expander('Practice marked flashcards', expanded=False):
            for index, (key, deck, card) in enumerate(cards):
                st.write(card['question'])
                revealed = st.checkbox('Show answer', key=f'home_card_reveal_{key}_{index}')
                if revealed:
                    st.write(card['answer'])
                    st.write(str(card.get('explanation', '')))
                st.button('Got it ✓', key=f'home_card_done_{key}_{index}', disabled=not revealed, on_click=mark_reviewed, args=(key, card['question']))
            if not cards:
                st.caption('Cards you mark “Practice again” will appear here.')
