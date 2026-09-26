"""Page callbacks run before Streamlit renders, avoiding an outgoing-page rerun."""
import streamlit as st


def toggle_navigation():
    st.session_state.nav_expanded = not st.session_state.get('nav_expanded', False)


def navigate_to(page):
    for flag, name in (
        ('subject_library_active', 'library'),
        ('edit_profile_active', 'profile'),
        ('leaderboard_active', 'leaderboard'),
        ('quiz_mode_active', 'quiz'),
    ):
        st.session_state[flag] = page == name
