"""Subject folders and an isolated, session-scoped mixed practice paper UI."""
import json
import uuid
from html import escape
import streamlit as st
import subject_library as library
from navigation import navigate_to


def open_course_material(doc):
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


def restore_saved_paper(paper_key, saved):
    import copy
    st.session_state[paper_key] = copy.deepcopy(saved)
    for question in saved['questions']:
        answer = saved.get('answers', {}).get(question['id'])
        st.session_state[f"paper_{saved['id']}_{question['id']}"] = answer if question['type'] == 'mcq' else (answer or '')


def discard_session_paper(paper_key):
    st.session_state.pop(paper_key, None)


def render_library(api_key):
    user = st.session_state.get('user') or {}
    uid, token = user.get('uid'), user.get('idToken')
    st.button('← Back to workspace', key='library_back', on_click=navigate_to, args=('workspace',))
    st.html('<div class="library-hero"><span>YOUR SUBJECT SPACE</span><h2>Organize. Connect. Practice.</h2><p>Keep your course materials together and turn them into a focused practice paper.</p></div>')
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
    if 'pending_subject_folder' in st.session_state:
        requested_folder = st.session_state.pop('pending_subject_folder')
        st.session_state[f'folder_browse_{uid}'] = requested_folder if requested_folder in folder_names else ''
    with st.container(key="library_subject_zone"):
        folder_id = st.selectbox('Browse subject', [''] + list(folder_names), format_func=lambda value: folder_names.get(value, 'Unfiled'), key=f'folder_browse_{uid}')
        folder_docs = [doc for doc in docs if doc.get('folder_id', '') == folder_id]
        st.html(f'<div class="subject-context"><span class="subject-context-icon" aria-hidden="true">▤</span><div><small>CURRENT SUBJECT</small><strong>{escape(folder_names.get(folder_id, "Unfiled"))}</strong></div><span class="subject-count">{len(folder_docs)} documents</span></div>')
    files_tab, paper_tab = st.tabs(['📂 Course materials', '✍️ Practice paper'])
    with files_tab:
        with st.container(key="library_manage_zone"):
            st.html('<div class="library-section-label"><span>01</span><div><strong>Your course materials</strong><p>Create folders, organize documents, or open a saved lecture.</p></div></div>')
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
        with st.container(key="library_browse_zone"):
            st.html('<div class="zone-heading"><span>▤</span><div><strong>Explore your materials</strong><small>Search your collection or choose a file from the shelf.</small></div></div>')
            if not folder_docs:
                st.info('This folder is empty. Save an analysis first, then use Organize documents to move it here.')
            search = st.text_input('Find a course material', placeholder='Search document titles…', key=f'library_search_{uid}_{folder_id}')
            visible_docs = [doc for doc in folder_docs if search.casefold() in doc.get('title', '').casefold()]
            if folder_docs:
                st.caption(f'{len(visible_docs)} of {len(folder_docs)} materials')
            if folder_docs and not visible_docs:
                st.info('No matching titles. Try a different search.')
            shelf_view = st.radio('Material view', ['Flowing shelf', 'Card grid'], horizontal=True, key='material_view')
            if shelf_view == 'Flowing shelf' and visible_docs:
                from pathlib import Path
                import streamlit.components.v1 as components
                carousel = components.declare_component('material_carousel', path=str(Path(__file__).with_name('material_carousel')))
                metadata = []
                for doc in visible_docs:
                    title = str(doc.get('title', 'Untitled'))
                    ext = title.rsplit('.', 1)[-1].lower() if '.' in title else ''
                    kind = {'pdf':'PDF', 'ppt':'SLIDES', 'pptx':'SLIDES', 'doc':'WORD', 'docx':'WORD'}.get(ext, 'NOTES')
                    metadata.append({'id':doc['id'], 'title':title.replace('_', ' '), 'kind':kind,
                        'tone':{'PDF':'rose', 'SLIDES':'blue', 'WORD':'mint', 'NOTES':'purple'}[kind],
                        'tools':[label for field, label in [('summary','Summary'), ('translation','Translation'), ('mindmap_eng','Mind map')] if doc.get(field)]})
                event = carousel(documents=metadata, key=f'material_shelf_{uid}_{folder_id}', default=None)
                if isinstance(event, dict) and event.get('event') != st.session_state.get('material_shelf_last_event'):
                    match = next((doc for doc in visible_docs if doc['id'] == event.get('id')), None)
                    if match is not None:
                        st.session_state.material_shelf_last_event = event.get('event')
                        open_course_material(match)
            for doc_index, doc in enumerate(visible_docs if shelf_view == 'Card grid' else []):
                if doc_index % 2 == 0:
                    document_columns = st.columns(2, gap="medium")
                with document_columns[doc_index % 2], st.container(key=f"course_material_card_{doc_index}", border=False):
                    title = str(doc.get('title', 'Untitled'))
                    extension = title.rsplit('.', 1)[-1].lower() if '.' in title else ''
                    file_kind = 'PDF' if extension == 'pdf' else ('SLIDES' if extension in ('ppt', 'pptx') else ('WORD' if extension in ('doc', 'docx') else 'NOTES'))
                    tone = {'PDF':'rose', 'SLIDES':'blue', 'WORD':'mint', 'NOTES':'purple'}[file_kind]
                    statuses = [label for field, label in [('summary','Summary'), ('translation','Translation'), ('mindmap_eng','Mind map')] if doc.get(field)]
                    badges = ''.join(f'<span>{label}</span>' for label in statuses) or '<span>Saved material</span>'
                    st.html(f'<div class="material-topline"><span class="material-file {tone}">{file_kind}</span><span class="material-saved">IN YOUR LIBRARY</span></div><h4 class="material-title" title="{escape(title, quote=True)}">{escape(title.replace("_", " "))}</h4><div class="material-badges">{badges}</div>')
                    if st.button('Open material →', key=f'folder_open_{doc["id"]}', use_container_width=True):
                        open_course_material(doc)
    with paper_tab, st.container(key="library_paper_zone"):
        st.html('<div class="library-section-label paper-section-label"><span>02</span><div><strong>Your practice paper</strong><p>Select materials, build a paper, then submit all answers together.</p></div></div>')
        st.caption('Save a draft to continue later, or save your marked paper for revision.')
        paper_key = f'subject_paper_{uid}'
        paper = st.session_state.get(paper_key)
        with st.expander('Saved papers · Continue or review'):
            if st.button('Load saved papers', key='load_saved_papers'):
                try:
                    st.session_state[f'saved_papers_{uid}'] = library.list_papers(uid, token)
                except Exception:
                    st.error('Could not load saved papers. Check your connection and account permissions.')
            saved_papers = st.session_state.get(f'saved_papers_{uid}', [])
            if f'saved_papers_{uid}' in st.session_state and not saved_papers:
                st.caption('No saved papers yet.')
            replace_allowed = not paper or st.checkbox('Replace the current session paper with a saved paper', key='replace_paper_allowed')
            for row in saved_papers:
                saved = row['paper']
                status = 'Marked' if saved.get('grades') else 'Draft'
                st.caption(f"{saved.get('folder', 'Subject')} · {status} · {row['updated_at'][:16].replace('T', ' ')} UTC")
                st.button('Open saved paper', key=f"restore_{saved['id']}", disabled=not replace_allowed, on_click=restore_saved_paper, args=(paper_key, saved))
        if not paper:
            candidates = {doc['id']: doc for doc in folder_docs}
            with st.expander('1 · Select course materials', expanded=True):
                source_ids = [doc_id for doc_id, doc in candidates.items() if st.checkbox(doc.get('title', doc_id), value=True, key=f'paper_source_{uid}_{folder_id}_{doc_id}')]
                st.caption(f'{len(source_ids)} of {len(candidates)} documents selected')
            st.markdown('#### 2 · Design your paper')
            mc_col, short_col, lang_col = st.columns(3)
            mcq_count = mc_col.selectbox('Multiple-choice questions', [4, 6, 8])
            short_count = short_col.selectbox('Short-answer questions', [2, 3, 4])
            language = lang_col.selectbox('Paper language', ['English', 'Chinese', 'Malay'])
            st.html(f'<div class="paper-blueprint"><div><small>MULTIPLE CHOICE</small><strong>{mcq_count} questions</strong><span>2 marks each</span></div><div><small>SHORT ANSWER</small><strong>{short_count} questions</strong><span>10 marks each</span></div><div><small>TOTAL</small><strong>{mcq_count * 2 + short_count * 10} marks</strong><span>{len(source_ids)} source documents</span></div></div>')
            if st.button('Generate mixed paper', type='primary', disabled=not source_ids or not api_key):
                try:
                    with st.spinner('Building a paper across your course materials…'):
                        progress = st.progress(0, text='Preparing questions…')
                        def show_progress(done, total, attempt):
                            text = 'Paper ready' if done == total else f'Question {done + 1} of {total}' + (f' · correcting attempt {attempt + 1}' if attempt else '')
                            progress.progress(done / total, text=text)
                        questions = library.generate_paper([candidates[x] for x in source_ids], api_key, language, mcq_count, short_count, on_progress=show_progress)
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
                    kind = question['type']
                    with st.container(key=f"paper_question_{kind}_{number}", border=False):
                        label = 'MULTIPLE CHOICE · Choose one' if kind == 'mcq' else 'SHORT ANSWER · Explain in your own words'
                        st.html(f'<div class="paper-question-label"><span>Q{number:02d}</span><strong>{label}</strong><small>{question["marks"]} marks</small></div>')
                        st.markdown(f'**{number}. {question["question"]}**')
                        st.caption(f'{question["marks"]} marks · ' + ' / '.join(paper['sources'][x] for x in question['sources']))
                        key = f'paper_{paper["id"]}_{question["id"]}'
                        # Streamlit removes widget state when leaving this page.
                        # Rehydrate saved/submitted answers when returning to it.
                        if key not in st.session_state:
                            saved_answer = paper.get('answers', {}).get(question['id'])
                            st.session_state[key] = saved_answer if question['type'] == 'mcq' else (saved_answer or '')
                        if question['type'] == 'mcq':
                            answers[question['id']] = st.radio('Select one answer', question['options'], index=None, key=key)
                        else:
                            answers[question['id']] = st.text_area('Your answer', height=150, max_chars=12000, key=key)
                st.caption('Unanswered questions receive 0 marks. Short answers receive AI practice feedback, not an official grade.')
                submit = st.form_submit_button('Submit paper for marking', type='primary')
                save_draft = st.form_submit_button('Save draft to account')
            if save_draft:
                paper['answers'] = answers
                try:
                    library.save_paper(uid, token, paper)
                except Exception:
                    st.error('Draft was not saved. Your answers remain here; please retry.')
                else:
                    st.session_state.pop(f'saved_papers_{uid}', None)
                    st.success('Draft saved to your account. Open Saved papers to continue later.')

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
                status = '✓ Full marks' if grade['score'] == question['marks'] else ('◐ Partial credit' if grade['score'] else '↻ Review')
                with st.expander(f'{number}. {question["question"]} · {grade["score"]}/{question["marks"]} · {status}'):
                    st.write('Your answer:', paper['answers'].get(question['id']) or 'Not answered')
                    st.write('Reference answer:', question['answer'])
                    st.write(grade['feedback'])
                    if question['type'] == 'short':
                        st.caption('AI assessment · ' + question['rubric'])
            if st.button('Save marked paper to account', key='save_marked_paper'):
                try:
                    library.save_paper(uid, token, paper)
                except Exception:
                    st.error('The marked paper was not saved. Please retry or download a copy.')
                else:
                    st.session_state.pop(f'saved_papers_{uid}', None)
                    st.success('Marked paper saved to your account.')
            st.download_button('Download marked paper', json.dumps(paper, ensure_ascii=False, indent=2), file_name='marked-practice-paper.json', mime='application/json')
        with st.expander('Start a different paper'):
            discard = st.checkbox('Discard this paper and its session answers', key=f'discard_{paper["id"]}')
            st.button('Start new paper', disabled=not discard, on_click=discard_session_paper, args=(paper_key,))
