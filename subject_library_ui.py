"""Subject folders and an isolated, session-scoped mixed practice paper UI."""
import json
import uuid
import streamlit as st
import subject_library as library


def render_library(api_key):
    user = st.session_state.get('user') or {}
    uid, token = user.get('uid'), user.get('idToken')
    if st.button('← Back to workspace', key='library_back'):
        st.session_state.subject_library_active = False
        st.rerun()
    st.markdown('## Subject library')
    st.caption('Group saved course materials by subject, then build one mixed practice paper from multiple documents.')
    if not uid or not token:
        st.info('Sign in to organize your saved documents.')
        return
    try:
        folders = library.list_folders(uid, token)
        docs = library.list_saved_documents(uid, token)
    except Exception:
        st.error('Could not load the subject library. Check your connection and account permissions, then retry.')
        if st.button('Retry loading library'):
            st.rerun()
        return
    folder_names = {folder['id']: folder['name'] for folder in folders}
    with st.expander('＋ Create a subject folder', expanded=not bool(folders)):
        with st.form('create_subject_folder'):
            name = st.text_input('Subject name', max_chars=80, placeholder='e.g. Quantum Computing')
            if st.form_submit_button('Create folder'):
                if name.strip().casefold() in {n.casefold() for n in folder_names.values()}:
                    st.warning('A folder with this name already exists.')
                else:
                    try:
                        library.create_folder(uid, token, name)
                    except Exception:
                        st.error('Folder was not created. Check the name, connection and account permissions.')
                    else:
                        st.rerun()
    folder_id = st.selectbox('Browse subject', [''] + list(folder_names), format_func=lambda value: folder_names.get(value, 'Unfiled'), key=f'folder_browse_{uid}')
    folder_docs = [doc for doc in docs if doc.get('folder_id', '') == folder_id]
    st.caption(f'{len(folder_docs)} documents · {folder_names.get(folder_id, "Unfiled")}')
    with st.expander('Organize documents'):
        st.caption('Move saved documents into this subject, or choose Unfiled to remove their classification. Contents are preserved.')
        doc_lookup = {doc['id']: doc for doc in docs}
        move_ids = st.multiselect('Documents to move', list(doc_lookup), format_func=lambda value: doc_lookup[value].get('title', value), key=f'move_docs_{uid}_{folder_id}')
        if st.button('Move to selected folder', disabled=not move_ids):
            try:
                library.move_documents(uid, token, move_ids, folder_id)
            except Exception:
                st.error('Documents were not moved. Please retry. Their contents have not been removed.')
            else:
                st.rerun()
    if not folder_docs:
        st.info('This folder is empty. Save an analysis first, then use Organize documents to move it here.')
    for doc in folder_docs:
        with st.container(border=True):
            st.write(doc.get('title', 'Untitled'))
            if st.button('Open document →', key=f'folder_open_{doc["id"]}'):
                st.session_state.ocr_results = dict(doc, filename=doc.get('title', 'Untitled'), lang=doc.get('language', 'Chinese'), time=0.0, is_loaded_from_db=True)
                try:
                    st.session_state[f'chat_history_{doc["id"]}'] = json.loads(doc.get('chat_history') or '[]')
                except (ValueError, TypeError):
                    st.session_state[f'chat_history_{doc["id"]}'] = []
                st.session_state.subject_library_active = False
                st.session_state.is_processing = False
                st.session_state.quiz_data = None
                st.session_state.quiz_mode_active = False
                st.rerun()
    st.divider()
    st.markdown('### Mixed practice paper')
    st.caption('Multiple choice + short answers · Submit the whole paper for marking. Paper and answers remain in this browser session only.')
    paper_key = f'subject_paper_{uid}'
    paper = st.session_state.get(paper_key)
    if not paper:
        candidates = {doc['id']: doc for doc in folder_docs}
        source_ids = st.multiselect('Course materials to include', list(candidates), default=list(candidates), format_func=lambda value: candidates[value].get('title', value), key=f'paper_sources_{uid}_{folder_id}')
        mc_col, short_col, lang_col = st.columns(3)
        mcq_count = mc_col.selectbox('Multiple-choice questions', [4, 6, 8])
        short_count = short_col.selectbox('Short-answer questions', [2, 3, 4])
        language = lang_col.selectbox('Paper language', ['English', 'Chinese', 'Malay'])
        st.caption(f'{mcq_count * 2 + short_count * 10} marks · Generated from the selected materials; larger files may require a smaller selection.')
        if st.button('Generate mixed paper', type='primary', disabled=not source_ids or not api_key):
            try:
                with st.spinner('Building a paper across your course materials…'):
                    questions = library.generate_paper([candidates[x] for x in source_ids], api_key, language, mcq_count, short_count)
                st.session_state[paper_key] = {'id': uuid.uuid4().hex, 'folder': folder_names.get(folder_id, 'Unfiled'), 'sources': {x: candidates[x].get('title', x) for x in source_ids}, 'questions': questions, 'answers': {}, 'grades': None}
            except Exception as exc:
                st.error(str(exc) if isinstance(exc, ValueError) else 'Paper generation failed. Please retry; no existing work was replaced.')
            else:
                paper = st.session_state[paper_key]
        if not api_key:
            st.info('Configure the AI API key to generate and mark papers.')
        if not paper:
            return
    st.markdown(f'#### {paper["folder"]} · Practice paper')
    with st.expander('Source materials'):
        for title in paper['sources'].values():
            st.write(title)
    if not paper['grades']:
        with st.form(f'paper_form_{paper["id"]}'):
            answers = {}
            for number, question in enumerate(paper['questions'], 1):
                st.markdown(f'**{number}. {question["question"]}**')
                st.caption(f'{question["marks"]} marks · ' + ' / '.join(paper['sources'][x] for x in question['sources']))
                key = f'paper_{paper["id"]}_{question["id"]}'
                if question['type'] == 'mcq':
                    answers[question['id']] = st.radio('Select one answer', question['options'], index=None, key=key)
                else:
                    answers[question['id']] = st.text_area('Your answer', height=150, max_chars=12000, key=key)
            st.caption('Unanswered questions receive 0 marks. Short answers receive AI practice feedback, not an official grade.')
            submit = st.form_submit_button('Submit paper for marking', type='primary')
        if submit:
            paper['answers'] = answers
            try:
                with st.spinner('Marking the complete paper…'):
                    paper['grades'] = library.grade_paper(paper['questions'], answers, api_key)
            except Exception:
                st.error('Marking could not be completed. Your answers are retained; submit again to retry.')
            else:
                st.rerun()
    else:
        earned = sum(row['score'] for row in paper['grades'].values())
        maximum = sum(q['marks'] for q in paper['questions'])
        st.success(f'Paper complete · {earned} / {maximum} marks')
        for number, question in enumerate(paper['questions'], 1):
            grade = paper['grades'][question['id']]
            with st.expander(f'{number}. {question["question"]} · {grade["score"]}/{question["marks"]}'):
                st.write('Your answer:', paper['answers'].get(question['id']) or 'Not answered')
                st.write('Reference answer:', question['answer'])
                st.write(grade['feedback'])
                if question['type'] == 'short':
                    st.caption('AI assessment · ' + question['rubric'])
        st.download_button('Download marked paper', json.dumps(paper, ensure_ascii=False, indent=2), file_name='marked-practice-paper.json', mime='application/json')
    with st.expander('Start a different paper'):
        discard = st.checkbox('Discard this paper and its session answers', key=f'discard_{paper["id"]}')
        if st.button('Start new paper', disabled=not discard):
            del st.session_state[paper_key]
            st.rerun()
