"""Page callbacks run before Streamlit renders, avoiding an outgoing-page rerun."""
import streamlit as st


def navigate_to(page):
    for flag, name in (
        ('subject_library_active', 'library'),
        ('edit_profile_active', 'profile'),
        ('leaderboard_active', 'leaderboard'),
        ('quiz_mode_active', 'quiz'),
    ):
        st.session_state[flag] = page == name
