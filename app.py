import sys
import warnings
import ssl

# Bypass SSL certificate verification for model downloads (e.g. on Streamlit Cloud)
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass

# Suppress non-critical warnings (like Google API Python 3.9 deprecation warnings)
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

if sys.version_info < (3, 10):
    try:
        import importlib_metadata
        import importlib.metadata
        if not hasattr(importlib.metadata, 'packages_distributions'):
            importlib.metadata.packages_distributions = importlib_metadata.packages_distributions
    except ImportError:
        pass

import streamlit as st
import streamlit.components.v1 as components
import time
import os
import base64
import json
from datetime import datetime

# Patch Streamlit's static index.html to disable the 'c' hotkey for clear cache (copy conflict)
def patch_streamlit_index_html():
    try:
        import os
        import streamlit as st
        streamlit_dir = os.path.dirname(st.__file__)
        index_path = os.path.join(streamlit_dir, "static", "index.html")
        if os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                html = f.read()
            if "preventClearCache" not in html and "</head>" in html:
                script = """    <!-- Prevent Streamlit's default keyboard shortcuts (like 'c' to clear cache) from interrupting Ctrl+C copy operations -->
    <script>
      (function() {
        const preventClearCache = function(e) {
          if (e.key.toLowerCase() === 'c') {
            const activeEl = document.activeElement;
            const isInput = activeEl && (
              activeEl.tagName === 'INPUT' ||
              activeEl.tagName === 'TEXTAREA' ||
              activeEl.isContentEditable ||
              (activeEl.shadowRoot && activeEl.shadowRoot.activeElement && (
                activeEl.shadowRoot.activeElement.tagName === 'INPUT' ||
                activeEl.shadowRoot.activeElement.tagName === 'TEXTAREA'
              ))
            );
            if (!isInput) {
              e.stopImmediatePropagation();
            }
          }
        };
        window.addEventListener('keydown', preventClearCache, true);
        document.addEventListener('keydown', preventClearCache, true);
      })();
    </script>
  </head>"""
                html = html.replace("</head>", script)
                with open(index_path, "w", encoding="utf-8") as f:
                    f.write(html)
    except Exception:
        pass

patch_streamlit_index_html()

# Patch Streamlit's main JS bundle to disable the 'c' keyboard shortcut (clear cache dialog)
def patch_streamlit_js_hotkeys():
    try:
        import os
        import glob
        import streamlit as st
        streamlit_dir = os.path.dirname(st.__file__)
        js_pattern = os.path.join(streamlit_dir, "static", "static", "js", "index.*.js")
        js_files = glob.glob(js_pattern)
        for js_path in js_files:
            with open(js_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            target_str = 'case"c":showDevelopmentOptions'
            if target_str in content:
                new_content = content.replace('case"c":showDevelopmentOptions', 'case"disabled_c":showDevelopmentOptions')
                with open(js_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
    except Exception:
        pass

patch_streamlit_js_hotkeys()


# Page Configuration
st.set_page_config(
    page_title="DocuMind MVP",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded"
)

@st.cache_resource(show_spinner=False)
def initialize_models():
    """Starts model pre-warming in a strictly non-blocking background thread."""
    import os
    if os.environ.get("HOME") == "/home/adminuser":
        # On Streamlit Cloud, we disable the background pre-warming thread
        # to prevent downloading race conditions and lock-ups.
        # The models will download safely in the main request thread when the first analysis starts.
        return True

    import threading
    def background_task():
        try:
            import time
            # 延迟 1.5 秒，让 Streamlit 主线程有充足的时间毫无阻力地完成主页面的前端渲染
            # 避免 PaddleOCR 模块加载时的 GIL 锁死导致页面卡顿
            time.sleep(1.5)
            
            # Import inside the thread to avoid blocking the main thread
            # Suppress standard output/error to prevent Streamlit I/O deadlocks 
            # caused by PaddleOCR's initial model download progress bars (tqdm).
            import sys, os
            _stdout, _stderr = sys.stdout, sys.stderr
            try:
                sys.stdout = open(os.devnull, 'w')
                sys.stderr = open(os.devnull, 'w')
                from ocr_engine import preload_models
                preload_models()
            finally:
                sys.stdout.close()
                sys.stderr.close()
                sys.stdout = _stdout
                sys.stderr = _stderr
        except Exception:
            pass
            
    thread = threading.Thread(target=background_task, daemon=True)
    thread.start()
    return True

# Removed immediate global background initialization here to avoid login page GIL contention.

import urllib.request
import urllib.error
import ssl

def save_summary_to_firestore(uid, id_token, title, raw_text, summary_text, translation_text=None, lang="Chinese", mindmap_eng="", mindmap_trans="", chat_history=None):
    """
    Saves a summary to the Firestore database via the REST API.
    """
    import urllib.parse
    
    # Sanitize title to make a valid Firestore document ID
    doc_id = title.replace("/", "-").replace("\\", "-").strip()
    if not doc_id:
        doc_id = "Summary"
    elif doc_id in (".", ".."):
        doc_id = f"doc_{doc_id}"
    elif doc_id.startswith("__") and doc_id.endswith("__"):
        doc_id = doc_id.strip("_")
        
    # Append timestamp to guarantee uniqueness and prevent Conflict errors
    timestamp_suffix = datetime.now().strftime('%Y%m%d_%H%M%S')
    doc_id_unique = f"{doc_id}_{timestamp_suffix}"
    
    quoted_doc_id = urllib.parse.quote(doc_id_unique)
    url = f"https://firestore.googleapis.com/v1/projects/fyp1-2772c/databases/(default)/documents/users/{uid}/summaries?documentId={quoted_doc_id}"
    
    # Structure of Firestore Document in REST API format
    fields = {
        "title": {"stringValue": title},
        "summary": {"stringValue": summary_text},
        "timestamp": {"stringValue": datetime.now().isoformat()}
    }
    if raw_text:
        fields["raw_text"] = {"stringValue": raw_text}
    if translation_text:
        fields["translation"] = {"stringValue": translation_text}
        fields["language"] = {"stringValue": lang}
    if mindmap_eng:
        fields["mindmap_eng"] = {"stringValue": mindmap_eng}
    if mindmap_trans:
        fields["mindmap_trans"] = {"stringValue": mindmap_trans}
    if chat_history:
        fields["chat_history"] = {"stringValue": json.dumps(chat_history, ensure_ascii=False)}
        
    data = {
        "fields": fields
    }
    
    headers = {
        "Content-Type": "application/json; charset=utf-8"
    }
    if id_token:
        headers["Authorization"] = f"Bearer {id_token}"
        
    req = urllib.request.Request(url, data=json.dumps(data, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
    ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            return True, doc_id_unique
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        # Try public write fallback in case the security rules are public
        try:
            req_public = urllib.request.Request(url, data=json.dumps(data, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
            with urllib.request.urlopen(req_public, context=ctx, timeout=10) as response:
                return True, doc_id_unique
        except Exception:
            return False, f"Database Error: {err_msg}"
    except Exception as e:
        return False, f"Connection Error: {str(e)}"

def save_chat_history_to_firestore(uid, doc_id, chat_history_list, id_token=None):
    """
    Saves the chat history list as a JSON string in the specific summary document.
    """
    import urllib.parse
    
    quoted_doc_id = urllib.parse.quote(doc_id)
    url = f"https://firestore.googleapis.com/v1/projects/fyp1-2772c/databases/(default)/documents/users/{uid}/summaries/{quoted_doc_id}?updateMask.fieldPaths=chat_history"
    
    chat_history_json = json.dumps(chat_history_list, ensure_ascii=False)
    
    data = {
        "fields": {
            "chat_history": {"stringValue": chat_history_json}
        }
    }
    
    headers = {
        "Content-Type": "application/json; charset=utf-8"
    }
    if id_token:
        headers["Authorization"] = f"Bearer {id_token}"
        
    req = urllib.request.Request(url, data=json.dumps(data, ensure_ascii=False).encode("utf-8"), headers=headers, method="PATCH")
    ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            return True, None
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        # Try public write fallback
        try:
            req_public = urllib.request.Request(url, data=json.dumps(data, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json; charset=utf-8"}, method="PATCH")
            with urllib.request.urlopen(req_public, context=ctx, timeout=10) as response:
                return True, None
        except Exception:
            return False, err_msg
    except Exception as e:
        return False, str(e)

def rename_document_title(uid, doc_id, new_title, id_token=None):
    """
    Updates the 'title' field of a saved summary document in Firestore.
    Uses PATCH with updateMask to only touch the title field.
    """
    import urllib.parse
    quoted_doc_id = urllib.parse.quote(doc_id, safe='')
    url = (
        f"https://firestore.googleapis.com/v1/projects/fyp1-2772c/databases/(default)/documents"
        f"/users/{uid}/summaries/{quoted_doc_id}?updateMask.fieldPaths=title"
    )
    data = {
        "fields": {
            "title": {"stringValue": new_title}
        }
    }
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if id_token:
        headers["Authorization"] = f"Bearer {id_token}"
    req = urllib.request.Request(
        url,
        data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="PATCH"
    )
    ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
            # Verify the returned title matches what we sent
            returned_title = result.get("fields", {}).get("title", {}).get("stringValue", "")
            if returned_title == new_title:
                return True, None
            else:
                return True, None  # Accept as success even if response differs
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        return False, f"HTTP {e.code}: {err_body[:200]}"
    except Exception as e:
        return False, f"Connection Error: {str(e)}"

def fetch_saved_summaries(uid, id_token=None):
    """
    Fetches all saved summaries from the Firestore database via the REST API.
    """
    url = f"https://firestore.googleapis.com/v1/projects/fyp1-2772c/databases/(default)/documents/users/{uid}/summaries"
    headers = {}
    if id_token:
        headers["Authorization"] = f"Bearer {id_token}"
        
    req = urllib.request.Request(url, headers=headers, method="GET")
    ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            documents = res_data.get("documents", [])
            parsed_docs = []
            for doc in documents:
                fields = doc.get("fields", {})
                name = doc.get("name", "")
                doc_id = name.split("/")[-1]
                parsed_docs.append({
                    "id": doc_id,
                    "title": fields.get("title", {}).get("stringValue", "Untitled"),
                    "raw_text": fields.get("raw_text", {}).get("stringValue", ""),
                    "summary": fields.get("summary", {}).get("stringValue", ""),
                    "translation": fields.get("translation", {}).get("stringValue", ""),
                    "language": fields.get("language", {}).get("stringValue", "Chinese"),
                    "mindmap_eng": fields.get("mindmap_eng", {}).get("stringValue", ""),
                    "mindmap_trans": fields.get("mindmap_trans", {}).get("stringValue", ""),
                    "chat_history": fields.get("chat_history", {}).get("stringValue", ""),
                    "timestamp": fields.get("timestamp", {}).get("stringValue", "")
                })
            # Sort by timestamp descending
            parsed_docs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return parsed_docs, None
    except urllib.error.HTTPError as e:
        # Try public read fallback
        try:
            req_public = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req_public, context=ctx, timeout=10) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                documents = res_data.get("documents", [])
                parsed_docs = []
                for doc in documents:
                    fields = doc.get("fields", {})
                    name = doc.get("name", "")
                    doc_id = name.split("/")[-1]
                    parsed_docs.append({
                        "id": doc_id,
                        "title": fields.get("title", {}).get("stringValue", "Untitled"),
                        "raw_text": fields.get("raw_text", {}).get("stringValue", ""),
                        "summary": fields.get("summary", {}).get("stringValue", ""),
                        "translation": fields.get("translation", {}).get("stringValue", ""),
                        "language": fields.get("language", {}).get("stringValue", "Chinese"),
                        "mindmap_eng": fields.get("mindmap_eng", {}).get("stringValue", ""),
                        "mindmap_trans": fields.get("mindmap_trans", {}).get("stringValue", ""),
                        "chat_history": fields.get("chat_history", {}).get("stringValue", ""),
                        "timestamp": fields.get("timestamp", {}).get("stringValue", "")
                    })
                parsed_docs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
                return parsed_docs, None
        except Exception:
            return [], e.read().decode("utf-8")
    except Exception as e:
        return [], str(e)

def delete_summary_from_firestore(uid, doc_id, id_token=None):
    """
    Deletes a saved summary from the Firestore database via the REST API.
    """
    import urllib.parse
    quoted_doc_id = urllib.parse.quote(doc_id)
    url = f"https://firestore.googleapis.com/v1/projects/fyp1-2772c/databases/(default)/documents/users/{uid}/summaries/{quoted_doc_id}"
    headers = {}
    if id_token:
        headers["Authorization"] = f"Bearer {id_token}"
        
    req = urllib.request.Request(url, headers=headers, method="DELETE")
    ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            return True, "Successfully deleted summary."
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        # Try public delete fallback
        try:
            req_public = urllib.request.Request(url, method="DELETE")
            with urllib.request.urlopen(req_public, context=ctx, timeout=10) as response:
                return True, "Successfully deleted summary."
        except Exception:
            return False, f"Database Error: {err_msg}"
def save_quiz_attempt(uid, id_token, attempt):
    """
    Saves a completed quiz attempt to the Firestore database.
    """
    import urllib.request
    import json
    import ssl
    from datetime import datetime
    
    # Structure of document fields
    answers_list = []
    for ans in attempt.get("answers", []):
        opt_values = [{"stringValue": o} for o in ans.get("options", [])]
        answers_list.append({
            "mapValue": {
                "fields": {
                    "question": {"stringValue": ans.get("question", "")},
                    "options": {"arrayValue": {"values": opt_values}},
                    "user_answer": {"stringValue": ans.get("user_answer", "")},
                    "correct_answer": {"stringValue": ans.get("correct_answer", "")},
                    "is_correct": {"booleanValue": ans.get("is_correct", False)},
                    "topic_tag": {"stringValue": ans.get("topic_tag", "General")},
                    "explanation": {"stringValue": ans.get("explanation", "")}
                }
            }
        })
        
    fields = {
        "attempt_id": {"stringValue": attempt.get("attempt_id", "")},
        "parent_attempt_id": {"stringValue": attempt.get("parent_attempt_id", "")},
        "date": {"stringValue": attempt.get("date", datetime.now().isoformat())},
        "topic": {"stringValue": attempt.get("topic", "General")},
        "difficulty": {"stringValue": attempt.get("difficulty", "Medium")},
        "score": {"integerValue": str(attempt.get("score", 0))},
        "total_questions": {"integerValue": str(attempt.get("total_questions", 10))},
        "time_taken_seconds": {"integerValue": str(attempt.get("time_taken_seconds", 0))},
        "time_limit_minutes": {"integerValue": str(attempt.get("time_limit_minutes", 0))},
        "xp_earned": {"integerValue": str(attempt.get("xp_earned", 0))},
        "is_retry": {"booleanValue": attempt.get("is_retry", False)},
        "answers": {"arrayValue": {"values": answers_list}}
    }
    
    data = {
        "fields": fields
    }
    
    attempt_id = attempt.get("attempt_id")
    url = f"https://firestore.googleapis.com/v1/projects/fyp1-2772c/databases/(default)/documents/users/{uid}/quiz_attempts?documentId={attempt_id}"
    
    headers = {
        "Content-Type": "application/json"
    }
    if id_token:
        headers["Authorization"] = f"Bearer {id_token}"
        
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
    ctx = ssl._create_unverified_context()
    
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            return True, "Quiz attempt saved to cloud account!"
    except Exception as e:
        try:
            req_public = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req_public, context=ctx, timeout=10) as response:
                return True, "Quiz attempt saved to cloud account!"
        except Exception as e_pub:
            return False, str(e_pub)

def fetch_quiz_attempts(uid, id_token=None):
    """
    Fetches all quiz attempts for the user from Firestore.
    """
    import urllib.request
    import json
    import ssl
    
    url = f"https://firestore.googleapis.com/v1/projects/fyp1-2772c/databases/(default)/documents/users/{uid}/quiz_attempts"
    headers = {}
    if id_token:
        headers["Authorization"] = f"Bearer {id_token}"
        
    req = urllib.request.Request(url, headers=headers, method="GET")
    ctx = ssl._create_unverified_context()
    
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            documents = res_data.get("documents", [])
            parsed_attempts = []
            for doc in documents:
                fields = doc.get("fields", {})
                
                # Parse answers
                answers_val = fields.get("answers", {}).get("arrayValue", {}).get("values", [])
                answers = []
                for a_val in answers_val:
                    a_fields = a_val.get("mapValue", {}).get("fields", {})
                    opt_vals = a_fields.get("options", {}).get("arrayValue", {}).get("values", [])
                    options = [o.get("stringValue", "") for o in opt_vals if o.get("stringValue")]
                    
                    answers.append({
                        "question": a_fields.get("question", {}).get("stringValue", ""),
                        "options": options,
                        "user_answer": a_fields.get("user_answer", {}).get("stringValue", ""),
                        "correct_answer": a_fields.get("correct_answer", {}).get("stringValue", ""),
                        "is_correct": a_fields.get("is_correct", {}).get("booleanValue", False),
                        "topic_tag": a_fields.get("topic_tag", {}).get("stringValue", "General"),
                        "explanation": a_fields.get("explanation", {}).get("stringValue", "")
                    })
                    
                parsed_attempts.append({
                    "attempt_id": fields.get("attempt_id", {}).get("stringValue", ""),
                    "parent_attempt_id": fields.get("parent_attempt_id", {}).get("stringValue", ""),
                    "date": fields.get("date", {}).get("stringValue", ""),
                    "topic": fields.get("topic", {}).get("stringValue", "General"),
                    "difficulty": fields.get("difficulty", {}).get("stringValue", "Medium"),
                    "score": int(fields.get("score", {}).get("integerValue", "0")),
                    "total_questions": int(fields.get("total_questions", {}).get("integerValue", "10")),
                    "time_taken_seconds": int(fields.get("time_taken_seconds", {}).get("integerValue", "0")),
                    "time_limit_minutes": int(fields.get("time_limit_minutes", {}).get("integerValue", "0")),
                    "xp_earned": int(fields.get("xp_earned", {}).get("integerValue", "0")),
                    "is_retry": fields.get("is_retry", {}).get("booleanValue", False),
                    "answers": answers
                })
            
            # Sort attempts by date descending
            parsed_attempts.sort(key=lambda x: x.get("date", ""), reverse=True)
            return parsed_attempts, None
            
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return [], None
        try:
            req_public = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req_public, context=ctx, timeout=10) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                documents = res_data.get("documents", [])
                parsed_attempts = []
                for doc in documents:
                    fields = doc.get("fields", {})
                    answers_val = fields.get("answers", {}).get("arrayValue", {}).get("values", [])
                    answers = []
                    for a_val in answers_val:
                        a_fields = a_val.get("mapValue", {}).get("fields", {})
                        opt_vals = a_fields.get("options", {}).get("arrayValue", {}).get("values", [])
                        options = [o.get("stringValue", "") for o in opt_vals if o.get("stringValue")]
                        answers.append({
                            "question": a_fields.get("question", {}).get("stringValue", ""),
                            "options": options,
                            "user_answer": a_fields.get("user_answer", {}).get("stringValue", ""),
                            "correct_answer": a_fields.get("correct_answer", {}).get("stringValue", ""),
                            "is_correct": a_fields.get("is_correct", {}).get("booleanValue", False),
                            "topic_tag": a_fields.get("topic_tag", {}).get("stringValue", "General"),
                            "explanation": a_fields.get("explanation", {}).get("stringValue", "")
                        })
                    parsed_attempts.append({
                        "attempt_id": fields.get("attempt_id", {}).get("stringValue", ""),
                        "parent_attempt_id": fields.get("parent_attempt_id", {}).get("stringValue", ""),
                        "date": fields.get("date", {}).get("stringValue", ""),
                        "topic": fields.get("topic", {}).get("stringValue", "General"),
                        "difficulty": fields.get("difficulty", {}).get("stringValue", "Medium"),
                        "score": int(fields.get("score", {}).get("integerValue", "0")),
                        "total_questions": int(fields.get("total_questions", {}).get("integerValue", "10")),
                        "time_taken_seconds": int(fields.get("time_taken_seconds", {}).get("integerValue", "0")),
                        "time_limit_minutes": int(fields.get("time_limit_minutes", {}).get("integerValue", "0")),
                        "xp_earned": int(fields.get("xp_earned", {}).get("integerValue", "0")),
                        "is_retry": fields.get("is_retry", {}).get("booleanValue", False),
                        "answers": answers
                    })
                parsed_attempts.sort(key=lambda x: x.get("date", ""), reverse=True)
                return parsed_attempts, None
        except Exception as e_pub:
            return [], str(e_pub)
    except Exception as e:
        return [], str(e)

def fetch_user_progression(uid, id_token=None):
    """
    Fetches the user's XP, level, and badges from the user document.
    """
    import urllib.request
    import json
    import ssl
    from datetime import datetime
    
    url = f"https://firestore.googleapis.com/v1/projects/fyp1-2772c/databases/(default)/documents/users/{uid}"
    headers = {}
    if id_token:
        headers["Authorization"] = f"Bearer {id_token}"
        
    req = urllib.request.Request(url, headers=headers, method="GET")
    ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            fields = res_data.get("fields", {})
            
            # Extract progression fields
            xp = int(fields.get("xp", {}).get("integerValue", "0"))
            level = int(fields.get("level", {}).get("integerValue", "1"))
            
            badges_val = fields.get("badges", {}).get("arrayValue", {}).get("values", [])
            badges = [b.get("stringValue", "") for b in badges_val if b.get("stringValue")]
            
            completed_quizzes = int(fields.get("completed_quizzes", {}).get("integerValue", "0"))
            last_updated = fields.get("last_updated", {}).get("stringValue", datetime.now().isoformat())
            
            return {
                "xp": xp,
                "level": level,
                "badges": badges,
                "completed_quizzes": completed_quizzes,
                "last_updated": last_updated
            }, None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"xp": 0, "level": 1, "badges": [], "completed_quizzes": 0, "last_updated": datetime.now().isoformat()}, None
        try:
            req_public = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req_public, context=ctx, timeout=10) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                fields = res_data.get("fields", {})
                xp = int(fields.get("xp", {}).get("integerValue", "0"))
                level = int(fields.get("level", {}).get("integerValue", "1"))
                badges_val = fields.get("badges", {}).get("arrayValue", {}).get("values", [])
                badges = [b.get("stringValue", "") for b in badges_val if b.get("stringValue")]
                completed_quizzes = int(fields.get("completed_quizzes", {}).get("integerValue", "0"))
                last_updated = fields.get("last_updated", {}).get("stringValue", datetime.now().isoformat())
                return {"xp": xp, "level": level, "badges": badges, "completed_quizzes": completed_quizzes, "last_updated": last_updated}, None
        except Exception as e_pub:
            return {"xp": 0, "level": 1, "badges": [], "completed_quizzes": 0, "last_updated": datetime.now().isoformat()}, str(e_pub)
    except Exception as e:
        return {"xp": 0, "level": 1, "badges": [], "completed_quizzes": 0, "last_updated": datetime.now().isoformat()}, str(e)

def update_user_xp_level(uid, id_token, additional_xp, new_badge=None, increment_quizzes=False, force_quizzes_count=None):
    """
    Updates the user's XP, level, and badges in the database.
    """
    import urllib.request
    import json
    import ssl
    from datetime import datetime
    
    progression, err = fetch_user_progression(uid, id_token)
    if err:
        return False, f"Failed to fetch progression: {err}"
    if not progression:
        progression = {"xp": 0, "level": 1, "badges": [], "completed_quizzes": 0, "last_updated": datetime.now().isoformat()}
        
    current_xp = progression.get("xp", 0)
    badges = progression.get("badges", [])
    completed_quizzes = progression.get("completed_quizzes", 0)
    
    # Calculate new XP
    updated_xp = current_xp + additional_xp
    
    # Calculate new Level
    updated_level = max(1, int(updated_xp // 500) + 1)
    
    # Add new badge if applicable and not already unlocked
    if new_badge and new_badge not in badges:
        badges.append(new_badge)
        
    # Check level milestones to unlock badges
    if updated_level >= 5 and "level_5_master" not in badges:
        badges.append("level_5_master")
    if updated_level >= 10 and "level_10_legend" not in badges:
        badges.append("level_10_legend")
        
    if force_quizzes_count is not None:
        completed_quizzes = force_quizzes_count
    elif increment_quizzes:
        completed_quizzes += 1
        
    # Update document with updateMask
    url = f"https://firestore.googleapis.com/v1/projects/fyp1-2772c/databases/(default)/documents/users/{uid}?updateMask.fieldPaths=xp&updateMask.fieldPaths=level&updateMask.fieldPaths=badges&updateMask.fieldPaths=completed_quizzes&updateMask.fieldPaths=last_updated"
    
    data = {
        "fields": {
            "xp": {"integerValue": str(updated_xp)},
            "level": {"integerValue": str(updated_level)},
            "badges": {
                "arrayValue": {
                    "values": [{"stringValue": b} for b in badges]
                }
            },
            "completed_quizzes": {"integerValue": str(completed_quizzes)},
            "last_updated": {"stringValue": datetime.now().isoformat()}
        }
    }
    
    headers = {
        "Content-Type": "application/json"
    }
    if id_token:
        headers["Authorization"] = f"Bearer {id_token}"
        
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="PATCH")
    ctx = ssl._create_unverified_context()
    
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            return True, {
                "xp": updated_xp,
                "level": updated_level,
                "badges": badges,
                "completed_quizzes": completed_quizzes,
                "last_updated": datetime.now().isoformat(),
                "xp_added": additional_xp,
                "level_up": (updated_level > progression.get("level", 1)),
                "badge_unlocked": (new_badge if new_badge and new_badge not in progression.get("badges", []) else None)
            }
    except Exception as e:
        try:
            req_public = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers={"Content-Type": "application/json"}, method="PATCH")
            with urllib.request.urlopen(req_public, context=ctx, timeout=10) as response:
                return True, {
                    "xp": updated_xp,
                    "level": updated_level,
                    "badges": badges,
                    "completed_quizzes": completed_quizzes,
                    "last_updated": datetime.now().isoformat(),
                    "xp_added": additional_xp,
                    "level_up": (updated_level > progression.get("level", 1)),
                    "badge_unlocked": (new_badge if new_badge and new_badge not in progression.get("badges", []) else None)
                }
        except Exception as e_pub:
            return False, str(e_pub)

def update_points(uid, id_token, points_to_add, increment_quizzes=False, force_quizzes_count=None):
    """
    Wrapper function to update the user's total points (XP) in Firestore.
    """
    return update_user_xp_level(uid, id_token, points_to_add, increment_quizzes=increment_quizzes, force_quizzes_count=force_quizzes_count)

def fetch_leaderboard(id_token=None):
    """
    Fetches all user documents from Firestore to build a real-time leaderboard.
    """
    import urllib.request
    import json
    import ssl
    from datetime import datetime
    
    url = "https://firestore.googleapis.com/v1/projects/fyp1-2772c/databases/(default)/documents/users?pageSize=100"
    headers = {}
    if id_token:
        headers["Authorization"] = f"Bearer {id_token}"
        
    req = urllib.request.Request(url, headers=headers, method="GET")
    ctx = ssl._create_unverified_context()
    
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            documents = res_data.get("documents", [])
            leaderboard_data = []
            
            for doc in documents:
                name_path = doc.get("name", "")
                uid = name_path.split("/")[-1] if name_path else ""
                if not uid:
                    continue
                    
                fields = doc.get("fields", {})
                
                # Fetch name, fallback to email prefix or anonymous if not set
                username = fields.get("name", {}).get("stringValue", "")
                if not username:
                    email_val = fields.get("email", {}).get("stringValue", "")
                    username = email_val.split("@")[0] if email_val else "Anonymous User"
                
                # Fetch points (stored as xp in progression)
                total_points = int(fields.get("xp", {}).get("integerValue", "0"))
                
                # Fetch completed quizzes count
                completed_quizzes = int(fields.get("completed_quizzes", {}).get("integerValue", "0"))
                
                # Fetch last updated time
                last_updated = fields.get("last_updated", {}).get("stringValue", "")
                if not last_updated:
                    # Fallback to document updateTime
                    last_updated = doc.get("updateTime", datetime.now().isoformat())
                
                leaderboard_data.append({
                    "user_id": uid,
                    "username": username,
                    "total_points": total_points,
                    "completed_quizzes": completed_quizzes,
                    "last_updated": last_updated
                })
            
            # Sort ranking rules:
            # 1. Total Points from high to low.
            # 2. If same points, then by Last Updated from newest to oldest.
            leaderboard_data.sort(
                key=lambda x: (x["total_points"], x["last_updated"]),
                reverse=True
            )
            return leaderboard_data, None
            
    except Exception as e:
        # Fallback to public request if token fails
        try:
            req_public = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req_public, context=ctx, timeout=10) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                documents = res_data.get("documents", [])
                leaderboard_data = []
                for doc in documents:
                    name_path = doc.get("name", "")
                    uid = name_path.split("/")[-1] if name_path else ""
                    if not uid:
                        continue
                    fields = doc.get("fields", {})
                    username = fields.get("name", {}).get("stringValue", "")
                    if not username:
                        email_val = fields.get("email", {}).get("stringValue", "")
                        username = email_val.split("@")[0] if email_val else "Anonymous User"
                    total_points = int(fields.get("xp", {}).get("integerValue", "0"))
                    completed_quizzes = int(fields.get("completed_quizzes", {}).get("integerValue", "0"))
                    last_updated = fields.get("last_updated", {}).get("stringValue", "")
                    if not last_updated:
                        last_updated = doc.get("updateTime", datetime.now().isoformat())
                    leaderboard_data.append({
                        "user_id": uid,
                        "username": username,
                        "total_points": total_points,
                        "completed_quizzes": completed_quizzes,
                        "last_updated": last_updated
                    })
                leaderboard_data.sort(
                    key=lambda x: (x["total_points"], x["last_updated"]),
                    reverse=True
                )
                return leaderboard_data, None
        except Exception as e_pub:
            return [], str(e_pub)

def fetch_user_details(uid, id_token=None):
    """
    Fetches the user document from the Firestore database via the REST API.
    """
    url = f"https://firestore.googleapis.com/v1/projects/fyp1-2772c/databases/(default)/documents/users/{uid}"
    headers = {}
    if id_token:
        headers["Authorization"] = f"Bearer {id_token}"
        
    req = urllib.request.Request(url, headers=headers, method="GET")
    ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            fields = res_data.get("fields", {})
            return {
                "name": fields.get("name", {}).get("stringValue", ""),
                "phone": fields.get("phone", {}).get("stringValue", ""),
                "role": fields.get("role", {}).get("stringValue", "Standard Account"),
                "bio": fields.get("bio", {}).get("stringValue", ""),
                "gender": fields.get("gender", {}).get("stringValue", "Prefer not to say"),
                "birth_date": fields.get("birth_date", {}).get("stringValue", ""),
                "joined_at": fields.get("joined_at", {}).get("stringValue", ""),
                "avatar": fields.get("avatar", {}).get("stringValue", ""),
                "exists": True
            }, None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"name": "", "phone": "", "role": "Standard Account", "bio": "", "gender": "Prefer not to say", "birth_date": "", "joined_at": "", "avatar": "", "exists": False}, None
        try:
            req_public = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req_public, context=ctx, timeout=10) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                fields = res_data.get("fields", {})
                return {
                    "name": fields.get("name", {}).get("stringValue", ""),
                    "phone": fields.get("phone", {}).get("stringValue", ""),
                    "role": fields.get("role", {}).get("stringValue", "Standard Account"),
                    "bio": fields.get("bio", {}).get("stringValue", ""),
                    "gender": fields.get("gender", {}).get("stringValue", "Prefer not to say"),
                    "birth_date": fields.get("birth_date", {}).get("stringValue", ""),
                    "joined_at": fields.get("joined_at", {}).get("stringValue", ""),
                    "avatar": fields.get("avatar", {}).get("stringValue", ""),
                    "exists": True
                }, None
        except urllib.error.HTTPError as e_pub:
            if e_pub.code == 404:
                return {"name": "", "phone": "", "role": "Standard Account", "bio": "", "gender": "Prefer not to say", "birth_date": "", "joined_at": "", "avatar": "", "exists": False}, None
            return None, e_pub.read().decode("utf-8")
        except Exception as e_pub:
            return None, str(e_pub)
    except Exception as e:
        return None, str(e)

def save_user_details(uid, id_token, name, phone="", role="Standard Account", bio="", gender="Prefer not to say", birth_date="", joined_at="", avatar=""):
    """
    Saves/Updates the user document in the Firestore database via the REST API.
    """
    url = f"https://firestore.googleapis.com/v1/projects/fyp1-2772c/databases/(default)/documents/users/{uid}?updateMask.fieldPaths=name&updateMask.fieldPaths=phone&updateMask.fieldPaths=role&updateMask.fieldPaths=bio&updateMask.fieldPaths=gender&updateMask.fieldPaths=birth_date&updateMask.fieldPaths=joined_at&updateMask.fieldPaths=avatar"
    data = {
        "fields": {
            "name": {"stringValue": name},
            "phone": {"stringValue": phone},
            "role": {"stringValue": role},
            "bio": {"stringValue": bio},
            "gender": {"stringValue": gender},
            "birth_date": {"stringValue": birth_date},
            "joined_at": {"stringValue": joined_at},
            "avatar": {"stringValue": avatar}
        }
    }
    headers = {
        "Content-Type": "application/json"
    }
    if id_token:
        headers["Authorization"] = f"Bearer {id_token}"
        
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="PATCH")
    ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            return True, "Profile details updated successfully!"
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        try:
            req_public = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers={"Content-Type": "application/json"}, method="PATCH")
            with urllib.request.urlopen(req_public, context=ctx, timeout=10) as response:
                return True, "Profile details updated successfully!"
        except Exception:
            return False, f"Database Error: {err_msg}"
def process_avatar_image(uploaded_file):
    try:
        from PIL import Image
        import io
        import base64
        
        img = Image.open(uploaded_file)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Downscale and compress
        img.thumbnail((128, 128))
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        img_bytes = buffer.getvalue()
        
        encoded = base64.b64encode(img_bytes).decode("utf-8")
        return f"data:image/jpeg;base64,{encoded}"
    except Exception:
        return None

def render_edit_profile_view():
    st.markdown("<br>", unsafe_allow_html=True)
    
    # Title Banner for Profile
    st.markdown("""
        <div style="background: linear-gradient(135deg, #e0e7ff 0%, #e9d5ff 50%, #fae8ff 100%); padding: 35px 20px; border-radius: 24px; text-align: center; margin-bottom: 2rem; border: 1px solid rgba(255, 255, 255, 0.6); box-shadow: 0 15px 35px -5px rgba(99, 102, 241, 0.08);">
            <h1 class="hero-title" style="margin: 0 !important; font-size: 3.2rem !important; background: linear-gradient(45deg, #f97316, #e11d48, #9f1239); -webkit-background-clip: text; -webkit-text-fill-color: transparent; line-height: 1.1;">Account Profile</h1>
            <p style="color: #4338ca; font-size: 1.05rem; margin-top: 0.6rem; font-weight: 600; letter-spacing: 0.3px;">Manage your profile information and account details</p>
        </div>
    """, unsafe_allow_html=True)

    # Main edit container style
    st.markdown("""
        <style>
        /* Overall profile container card styling */
        div[class*="st-key-profile_container"] {
            background: rgba(255, 255, 255, 0.85) !important;
            border: 1px solid rgba(226, 232, 240, 0.8) !important;
            border-radius: 24px !important;
            padding: 35px 40px !important;
            backdrop-filter: blur(20px) !important;
            box-shadow: 0 20px 40px -15px rgba(99, 102, 241, 0.04) !important;
            margin-bottom: 2rem !important;
        }

        /* Style text inputs, textareas and selectbox buttons inside profile */
        div[class*="st-key-profile_container"] div[data-testid="stTextInput"] input,
        div[class*="st-key-profile_container"] div[data-testid="stTextArea"] textarea,
        div[class*="st-key-profile_container"] div[data-testid="stSelectbox"] div[role="button"] {
            border-radius: 12px !important;
            border: 1px solid #cbd5e1 !important;
            background-color: #ffffff !important;
            padding: 12px 16px !important;
            font-size: 1.05rem !important;
            transition: all 0.2s ease !important;
        }
        div[class*="st-key-profile_container"] div[data-testid="stTextInput"] input:focus,
        div[class*="st-key-profile_container"] div[data-testid="stTextArea"] textarea:focus,
        div[class*="st-key-profile_container"] div[data-testid="stSelectbox"] div[role="button"]:focus {
            border-color: #6366f1 !important;
            box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1) !important;
            outline: none !important;
        }
        
        /* Style input field labels */
        div[class*="st-key-profile_container"] label[data-testid="stWidgetLabel"] p {
            font-size: 1.08rem !important;
            font-weight: 600 !important;
            color: #334155 !important;
            margin-bottom: 6px !important;
        }
        
        /* Make read-only/disabled text inputs look distinct and clean */
        div[class*="st-key-profile_container"] div[data-testid="stTextInput"] input:disabled {
            background-color: #f8fafc !important;
            color: #64748b !important;
            border-color: #e2e8f0 !important;
            cursor: not-allowed !important;
        }

        /* Style custom file uploader */
        div[class*="st-key-profile_container"] div[data-testid="stFileUploader"] {
            border: 2px dashed rgba(99, 102, 241, 0.25) !important;
            background-color: rgba(99, 102, 241, 0.01) !important;
            border-radius: 16px !important;
            padding: 12px !important;
            transition: all 0.2s ease !important;
        }
        div[class*="st-key-profile_container"] div[data-testid="stFileUploader"]:hover {
            border-color: #6366f1 !important;
            background-color: rgba(99, 102, 241, 0.03) !important;
        }

        /* Action buttons style overrides */
        div[class*="st-key-profile_cancel_btn"] button {
            background-color: #ffffff !important;
            color: #475569 !important;
            border: 1px solid #cbd5e1 !important;
            border-radius: 12px !important;
            padding: 10px 24px !important;
            font-size: 1.08rem !important;
            font-weight: 600 !important;
            transition: all 0.2s ease !important;
            height: 44px !important;
        }
        div[class*="st-key-profile_cancel_btn"] button:hover {
            background-color: #f8fafc !important;
            color: #0f172a !important;
            border-color: #94a3b8 !important;
        }

        div[class*="st-key-profile_save_btn"] button {
            background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%) !important;
            color: #ffffff !important;
            border: none !important;
            border-radius: 12px !important;
            padding: 10px 24px !important;
            font-size: 1.08rem !important;
            font-weight: 700 !important;
            box-shadow: 0 4px 14px rgba(99, 102, 241, 0.2) !important;
            transition: all 0.2s ease !important;
            height: 44px !important;
        }
        div[class*="st-key-profile_save_btn"] button:hover {
            background: linear-gradient(135deg, #4f46e5 0%, #4338ca 100%) !important;
            box-shadow: 0 6px 20px rgba(99, 102, 241, 0.3) !important;
            transform: translateY(-1px);
        }

        /* Style the Remove Avatar button */
        div[class*="st-key-remove_avatar_btn"] button {
            background-color: rgba(239, 68, 68, 0.04) !important;
            color: #ef4444 !important;
            border: 1px solid rgba(239, 68, 68, 0.15) !important;
            border-radius: 10px !important;
            font-size: 0.85rem !important;
            font-weight: 600 !important;
            transition: all 0.2s ease !important;
        }
        div[class*="st-key-remove_avatar_btn"] button:hover {
            background-color: #ef4444 !important;
            color: #ffffff !important;
            border-color: #ef4444 !important;
        }
        </style>
    """, unsafe_allow_html=True)
    
    # Fetch details from session state
    user_info = st.session_state.get('user', {})
    uid = user_info.get("uid")
    id_token = user_info.get("idToken")
    curr_email = user_info.get('email', '')
    
    user_profile = st.session_state.get('user_profile', {})
    curr_name = user_profile.get('name') or user_info.get('name', '')
    curr_phone = user_profile.get('phone', '')
    curr_role = user_profile.get('role', 'Standard Account')
    curr_bio = user_profile.get('bio', '')
    curr_gender = user_profile.get('gender', 'Prefer not to say')
    curr_birth_date = user_profile.get('birth_date', '')
    curr_joined_at = user_profile.get('joined_at', '') or datetime.now().strftime("%B %d, %Y")
    
    # Initialize temp avatar for editing
    if 'temp_avatar' not in st.session_state:
        st.session_state.temp_avatar = user_profile.get('avatar', '')
    
    # Form layout inside streamlit container
    with st.container(key="profile_container", border=True):
        # Avatar Profile Summary Header
        profile_avatar = st.session_state.temp_avatar
        initials = curr_name[0].upper() if curr_name else "U"
        
        avatar_header_html = ""
        if profile_avatar:
            avatar_header_html = f'<img src="{profile_avatar}" style="width: 76px; height: 76px; border-radius: 50%; object-fit: cover; border: 3px solid #6366F1; box-shadow: 0 8px 20px rgba(99, 102, 241, 0.2);">'
        else:
            avatar_header_html = f'<div style="width: 76px; height: 76px; border-radius: 50%; background: linear-gradient(135deg, #6366F1 0%, #8B5CF6 100%); color: white; display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 2rem; font-family: \'Poppins\', sans-serif; box-shadow: 0 8px 20px rgba(99, 102, 241, 0.2);">{initials}</div>'
            
        st.markdown(f"""
            <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 20px; padding: 24px; display: flex; align-items: center; gap: 24px; margin-bottom: 24px; box-shadow: 0 10px 25px -5px rgba(99, 102, 241, 0.03); flex-wrap: wrap;">
                {avatar_header_html}
                <div>
                    <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
                        <h2 style="margin: 0; font-size: 1.7rem; font-weight: 800; color: #0f172a; font-family: 'Poppins', sans-serif; line-height: 1.2;">{curr_name}</h2>
                        <span style="background: linear-gradient(45deg, #f97316, #e11d48, #9f1239); color: white; font-size: 0.72rem; font-weight: 700; padding: 2px 10px; border-radius: 99px; box-shadow: 0 4px 10px rgba(225, 29, 72, 0.15); display: inline-flex; align-items: center;">PRO MEMBER</span>
                    </div>
                    <p style="margin: 6px 0 0 0; color: #64748b; font-size: 0.9rem; font-weight: 500;">Account: <span style="color:#6366f1; font-weight:600;">{curr_role}</span> • Joined on {curr_joined_at}</p>
                </div>
            </div>
        """, unsafe_allow_html=True)
        
        # User Stats Dashboard Widgets in Profile
        s_col1, s_col2, s_col3 = st.columns(3)
        with s_col1:
            st.markdown("""
                <div style="background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%); border: 1px solid #bbf7d0; border-radius: 16px; padding: 16px 20px; display: flex; flex-direction: column; justify-content: center; box-shadow: 0 4px 15px rgba(16, 185, 129, 0.03); min-height: 75px;">
                    <div style="font-size: 0.76rem; font-weight: 700; color: #166534; text-transform: uppercase; letter-spacing: 0.05em;">API Status</div>
                    <div style="display: flex; align-items: center; gap: 8px; margin-top: 6px;">
                        <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background-color: #10b981; box-shadow: 0 0 8px #10b981;"></span>
                        <span style="font-size: 1.05rem; font-weight: 800; color: #14532d;">Connected</span>
                    </div>
                </div>
            """, unsafe_allow_html=True)
        with s_col2:
            st.markdown("""
                <div style="background: linear-gradient(135deg, #faf5ff 0%, #f3e8ff 100%); border: 1px solid #e9d5ff; border-radius: 16px; padding: 16px 20px; display: flex; flex-direction: column; justify-content: center; box-shadow: 0 4px 15px rgba(139, 92, 246, 0.03); min-height: 75px;">
                    <div style="font-size: 0.76rem; font-weight: 700; color: #581c87; text-transform: uppercase; letter-spacing: 0.05em;">Engine Tier</div>
                    <div style="font-size: 1.05rem; font-weight: 800; color: #6b21a8; margin-top: 6px;">Gemini Pro 1.5</div>
                </div>
            """, unsafe_allow_html=True)
        with s_col3:
            st.markdown("""
                <div style="background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%); border: 1px solid #bae6fd; border-radius: 16px; padding: 16px 20px; display: flex; flex-direction: column; justify-content: center; box-shadow: 0 4px 15px rgba(59, 130, 246, 0.03); min-height: 75px;">
                    <div style="font-size: 0.76rem; font-weight: 700; color: #075985; text-transform: uppercase; letter-spacing: 0.05em;">Account Status</div>
                    <div style="font-size: 1.05rem; font-weight: 800; color: #0c4a6e; margin-top: 6px;">Active Verified</div>
                </div>
            """, unsafe_allow_html=True)

        st.markdown("<div style='height: 25px;'></div>", unsafe_allow_html=True)
        
        # Row 0: Customize Profile Avatar
        st.markdown("""
            <div style="display: flex; align-items: center; gap: 8px; border-left: 4px solid #6366f1; padding-left: 12px; margin-top: 10px; margin-bottom: 18px;">
                <h4 style="font-size: 1.45rem; font-weight: 800; color: #0f172a; margin: 0; font-family: 'Poppins', sans-serif;">🖼️ Customize Profile Avatar</h4>
            </div>
        """, unsafe_allow_html=True)
        
        avatar_col1, avatar_col2 = st.columns([1.5, 3.5])
        with avatar_col1:
            # Render the preview card cleanly
            if st.session_state.temp_avatar:
                st.markdown(f"""
                    <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 20px; padding: 20px; box-shadow: 0 8px 20px rgba(0, 0, 0, 0.02); min-height: 180px;">
                        <img src="{st.session_state.temp_avatar}" style="width: 110px; height: 110px; border-radius: 50%; object-fit: cover; border: 4px solid #6366F1; box-shadow: 0 8px 24px rgba(99, 102, 241, 0.12); margin-bottom: 12px;">
                    </div>
                """, unsafe_allow_html=True)
                if st.button("❌ Remove Avatar", use_container_width=True, key="remove_avatar_btn"):
                    st.session_state.temp_avatar = ""
                    if 'last_processed_avatar' in st.session_state:
                        del st.session_state.last_processed_avatar
                    st.rerun()
            else:
                st.markdown(f"""
                    <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 20px; padding: 20px; box-shadow: 0 8px 20px rgba(0, 0, 0, 0.02); min-height: 180px;">
                        <div style="width: 110px; height: 110px; border-radius: 50%; background: linear-gradient(135deg, #6366F1 0%, #8B5CF6 100%); color: white; display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 2.8rem; font-family: 'Poppins', sans-serif; box-shadow: 0 8px 24px rgba(99, 102, 241, 0.12); margin-bottom: 12px;">{initials}</div>
                    </div>
                """, unsafe_allow_html=True)
                    
        with avatar_col2:
            AVATAR_PRESETS = {
                "Use Initials (Default)": "",
                "✨ Cosmic Rocket": "data:image/svg+xml;utf8,<svg viewBox='0 0 100 100' xmlns='http://www.w3.org/2000/svg'><defs><linearGradient id='gRocket' x1='0%25' y1='0%25' x2='100%25' y2='100%25'><stop offset='0%25' stop-color='%23EC4899'/><stop offset='100%25' stop-color='%23F43F5E'/></linearGradient></defs><circle cx='50' cy='50' r='50' fill='url(%23gRocket)'/><path d='M50 25c-3 8-5 15-5 25 0 15 5 25 5 25s5-10 5-25c0-10-2-17-5-25z' fill='white'/><path d='M40 55c-2 6-2 12 0 15 3 0 6-3 8-8zM60 55c2 6 2 12 0 15-3 0-6-3-8-8z' fill='white' opacity='0.7'/></svg>",
                "🧠 AI Intelligence": "data:image/svg+xml;utf8,<svg viewBox='0 0 100 100' xmlns='http://www.w3.org/2000/svg'><defs><linearGradient id='gBrain' x1='0%25' y1='0%25' x2='100%25' y2='100%25'><stop offset='0%25' stop-color='%238B5CF6'/><stop offset='100%25' stop-color='%236366F1'/></linearGradient></defs><circle cx='50' cy='50' r='50' fill='url(%23gBrain)'/><path d='M38 42c-4 0-7 3-7 7 0 2 1 4 2 5-1 1-2 2-2 4 0 3 2 6 5 6h1c0 3 3 5 6 5s6-2 6-5h1c3 0 5-3 5-6 0-2-1-3-2-4 1-1 2-3 2-5 0-4-3-7-7-7zm24 0c-4 0-7 3-7 7 0 2 1 3 2 4-1 1-2 2-2 5 0 3 2 6 5 6h1c0 3 3 5 6 5s6-2 6-5h1c3 0 5-3 5-6 0-2-1-3-2-4 1-1 2-2 2-4 0-4-3-7-7-7z' fill='white' opacity='0.9'/></svg>",
                "💻 Tech Developer": "data:image/svg+xml;utf8,<svg viewBox='0 0 100 100' xmlns='http://www.w3.org/2000/svg'><defs><linearGradient id='gDev' x1='0%25' y1='0%25' x2='100%25' y2='100%25'><stop offset='0%25' stop-color='%2306B6D4'/><stop offset='100%25' stop-color='%233B82F6'/></linearGradient></defs><circle cx='50' cy='50' r='50' fill='url(%23gDev)'/><path d='M35 40l-15 10 15 10M65 40l15 10-15 10M45 65l10-30' stroke='white' stroke-width='6' stroke-linecap='round' stroke-linejoin='round' fill='none'/></svg>",
                "⚡ Cyber Speed": "data:image/svg+xml;utf8,<svg viewBox='0 0 100 100' xmlns='http://www.w3.org/2000/svg'><defs><linearGradient id='gLightning' x1='0%25' y1='0%25' x2='100%25' y2='100%25'><stop offset='0%25' stop-color='%23FBBF24'/><stop offset='100%25' stop-color='%23F59E0B'/></linearGradient></defs><circle cx='50' cy='50' r='50' fill='url(%23gLightning)'/><path d='M55 25L35 50h15L45 75l20-25H50z' fill='white'/></svg>",
                "🎓 Academic Scholar": "data:image/svg+xml;utf8,<svg viewBox='0 0 100 100' xmlns='http://www.w3.org/2000/svg'><defs><linearGradient id='gGrad' x1='0%25' y1='0%25' x2='100%25' y2='100%25'><stop offset='0%25' stop-color='%2310B981'/><stop offset='100%25' stop-color='%23059669'/></linearGradient></defs><circle cx='50' cy='50' r='50' fill='url(%23gGrad)'/><path d='M50 28L25 40l25 12 25-12zM32 46v12c0 5 8 8 18 8s18-3 18-8V46M71 42v15' stroke='white' stroke-width='4' stroke-linecap='round' stroke-linejoin='round' fill='none'/></svg>"
            }
            preset_names = list(AVATAR_PRESETS.keys())
            current_preset_idx = 0
            for name, val in AVATAR_PRESETS.items():
                if val and st.session_state.temp_avatar == val:
                    current_preset_idx = preset_names.index(name)
                    break
            
            selected_preset = st.selectbox("🎭 Select Premium Preset", options=preset_names, index=current_preset_idx, help="Choose one of our premium stylized vector avatars.")
            if AVATAR_PRESETS[selected_preset] != st.session_state.temp_avatar:
                if AVATAR_PRESETS[selected_preset] or st.session_state.temp_avatar in AVATAR_PRESETS.values():
                    st.session_state.temp_avatar = AVATAR_PRESETS[selected_preset]
                    if 'last_processed_avatar' in st.session_state:
                        del st.session_state.last_processed_avatar
                    st.rerun()
            
            uploaded_avatar = st.file_uploader("📤 Or Upload Custom Image", type=["png", "jpg", "jpeg"], help="Upload an image (PNG/JPG). It will be auto-resized and compressed.")
            if uploaded_avatar is not None:
                file_key = f"avatar_{uploaded_avatar.name}_{uploaded_avatar.size}"
                if st.session_state.get("last_processed_avatar") != file_key:
                    with st.spinner("Processing avatar..."):
                        base64_avatar = process_avatar_image(uploaded_avatar)
                        if base64_avatar:
                            st.session_state.temp_avatar = base64_avatar
                            st.session_state.last_processed_avatar = file_key
                            st.rerun()
                        else:
                            st.error("Failed to process image. Please try another one.")

        # Personal Details Section Header
        st.markdown("""
            <div style="display: flex; align-items: center; gap: 8px; border-left: 4px solid #8b5cf6; padding-left: 12px; margin-top: 25px; margin-bottom: 18px;">
                <h4 style="font-size: 1.45rem; font-weight: 800; color: #0f172a; margin: 0; font-family: 'Poppins', sans-serif;">📝 Personal Information</h4>
            </div>
        """, unsafe_allow_html=True)
        
        # Row 1: Display Name & Email Address
        r1_col1, r1_col2 = st.columns(2)
        with r1_col1:
            new_name = st.text_input("👤 Display Name", value=curr_name, placeholder="Enter your full name", help="Your custom display name shown in the sidebar.")
        with r1_col2:
            st.text_input("✉️ Email Address (Read-Only)", value=curr_email, disabled=True, help="Your account login email (cannot be modified).")
        
        # Row 2: Contact Number & Gender
        r2_col1, r2_col2 = st.columns(2)
        with r2_col1:
            new_phone = st.text_input("📞 Contact Number", value=curr_phone, placeholder="+6012-3456789", help="Optional phone number.")
        with r2_col2:
            gender_options = ["Prefer not to say", "Male", "Female", "Other"]
            default_gender_idx = 0
            if curr_gender in gender_options:
                default_gender_idx = gender_options.index(curr_gender)
            new_gender = st.selectbox("🚻 Gender", options=gender_options, index=default_gender_idx, help="Your gender identification.")
            
        # Row 3: Role / Designation & Date of Birth
        r3_col1, r3_col2 = st.columns(2)
        with r3_col1:
            roles_list = ["Standard Account", "Student", "Lecturer", "Researcher", "Developer", "Guest"]
            default_role_idx = 0
            if curr_role in roles_list:
                default_role_idx = roles_list.index(curr_role)
            else:
                roles_list.append(curr_role)
                default_role_idx = len(roles_list) - 1
            new_role = st.selectbox("🎓 Role / Designation", options=roles_list, index=default_role_idx, help="Your role in your institution.")
        with r3_col2:
            new_birth_date = st.text_input("📅 Date of Birth", value=curr_birth_date, placeholder="YYYY-MM-DD", help="Format: YYYY-MM-DD")
            
        # Row 4: Registration Date & Biography
        r4_col1, r4_col2 = st.columns(2)
        with r4_col1:
            st.text_input("📅 Registration Date (Read-Only)", value=curr_joined_at, disabled=True, help="The date your account profile was created.")
        with r4_col2:
            st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
            
        # Biography
        new_bio = st.text_area("📝 Biography / Notes", value=curr_bio, placeholder="Tell us about yourself...", help="Short bio or notes.")
        
        st.markdown("<hr style='border: 0; border-top: 1px solid #e2e8f0; margin: 24px 0;'>", unsafe_allow_html=True)
        
        # Action buttons
        btn_col1, btn_col2 = st.columns([1, 4])
        with btn_col1:
            if st.button("Cancel", use_container_width=True, key="profile_cancel_btn"):
                if 'temp_avatar' in st.session_state:
                    del st.session_state.temp_avatar
                if 'last_processed_avatar' in st.session_state:
                    del st.session_state.last_processed_avatar
                st.session_state.edit_profile_active = False
                st.rerun()
        with btn_col2:
            if st.button("Save Changes ✓", type="primary", use_container_width=True, key="profile_save_btn"):
                if not new_name.strip():
                    st.error("Display Name cannot be empty.")
                else:
                    with st.spinner("Saving changes to Firestore..."):
                        success, msg = save_user_details(
                            uid=uid,
                            id_token=id_token,
                            name=new_name.strip(),
                            phone=new_phone.strip(),
                            role=new_role,
                            bio=new_bio.strip(),
                            gender=new_gender,
                            birth_date=new_birth_date.strip(),
                            joined_at=curr_joined_at,
                            avatar=st.session_state.temp_avatar
                        )
                        if success:
                            # Update local session profile
                            st.session_state.user_profile = {
                                "name": new_name.strip(),
                                "phone": new_phone.strip(),
                                "role": new_role,
                                "bio": new_bio.strip(),
                                "gender": new_gender,
                                "birth_date": new_birth_date.strip(),
                                "joined_at": curr_joined_at,
                                "avatar": st.session_state.temp_avatar,
                                "exists": True
                            }
                            if 'temp_avatar' in st.session_state:
                                del st.session_state.temp_avatar
                            if 'last_processed_avatar' in st.session_state:
                                del st.session_state.last_processed_avatar
                            st.session_state.edit_profile_active = False
                            st.toast("Profile updated successfully!", icon="✅")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(msg)

def render_leaderboard_view():
    import streamlit as st
    from datetime import datetime
    import time
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # Title Banner for Leaderboard
    st.markdown("""<div style="background: linear-gradient(135deg, #e0e7ff 0%, #e9d5ff 50%, #fae8ff 100%); padding: 35px 20px; border-radius: 24px; text-align: center; margin-bottom: 2rem; border: 1px solid rgba(255, 255, 255, 0.6); box-shadow: 0 15px 35px -5px rgba(99, 102, 241, 0.08);">
    <h1 class="hero-title" style="margin: 0 !important; font-size: 3.2rem !important; background: linear-gradient(45deg, #f97316, #e11d48, #9f1239); -webkit-background-clip: text; -webkit-text-fill-color: transparent; line-height: 1.1;">🏆 Global Leaderboard</h1>
    <p style="color: #4338ca; font-size: 1.15rem; margin-top: 0.6rem; font-weight: 600; letter-spacing: 0.3px;">Real-time ranking of top scholars. Complete quizzes to climb the board!</p>
</div>""", unsafe_allow_html=True)
    
    user_info = st.session_state.get("user")
    uid = user_info.get("uid") if user_info else None
    id_token = user_info.get("idToken") if user_info else None
    
    if not uid:
        st.warning("⚠️ You must be logged in to view the leaderboard.")
        if st.button("↩️ Back to Home", use_container_width=True, type="primary", key="lbl_back_home_guest"):
            st.session_state.leaderboard_active = False
            st.rerun()
        return
        
    with st.spinner("Fetching leaderboard data from cloud..."):
        leaderboard_data, err = fetch_leaderboard(id_token)
        
    if err:
        st.error(f"Failed to load leaderboard: {err}")
        if st.button("↩️ Back to Home", use_container_width=True, type="primary", key="lbl_back_home_err"):
            st.session_state.leaderboard_active = False
            st.rerun()
        return

    # Find current user's stats
    user_rank = None
    user_points = 0
    user_quizzes = 0
    points_gap = None
    
    # Look up in the sorted rankings
    for index, u in enumerate(leaderboard_data):
        if u["user_id"] == uid:
            user_rank = index + 1
            user_points = u["total_points"]
            user_quizzes = u["completed_quizzes"]
            
            # Find gap with the user above them
            if index > 0:
                above_user = leaderboard_data[index - 1]
                points_gap = above_user["total_points"] - user_points
            break

    # If user has no record in the leaderboard yet, they are 0 points and unranked (or at the bottom)
    if user_rank is None:
        user_points = 0
        user_quizzes = 0
        if leaderboard_data:
            # Put them at the end
            user_rank = len(leaderboard_data) + 1
            points_gap = leaderboard_data[-1]["total_points"] - user_points
        else:
            user_rank = 1
            points_gap = 0

    # Top Section: User's Standing Card (Dashboard style)
    gap_text = f"🔥 {points_gap} XP gap to next rank" if points_gap and points_gap > 0 else "👑 You are at the top!"
    st.markdown(f"""<div style="background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 20px; padding: 28px; margin-bottom: 24px; box-shadow: 0 4px 6px rgba(0,0,0,0.02); display: flex; flex-direction: row; flex-wrap: wrap; justify-content: space-around; gap: 20px; align-items: center;">
    <div style="text-align: center; min-width: 130px;">
        <div style="font-size: 1.05rem; font-weight: 600; color: #64748B; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px;">Your Rank</div>
        <div style="font-size: 2.8rem; font-weight: 800; color: #6366f1;">#{user_rank}</div>
    </div>
    <div style="width: 1px; height: 60px; background-color: #E2E8F0; display: inline-block;"></div>
    <div style="text-align: center; min-width: 130px;">
        <div style="font-size: 1.05rem; font-weight: 600; color: #64748B; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px;">Total Points</div>
        <div style="font-size: 2.8rem; font-weight: 800; color: #0f172a;">{user_points} <span style="font-size: 1.3rem; color: #8b5cf6; font-weight: 700;">XP</span></div>
    </div>
    <div style="width: 1px; height: 60px; background-color: #E2E8F0; display: inline-block;"></div>
    <div style="text-align: center; min-width: 130px;">
        <div style="font-size: 1.05rem; font-weight: 600; color: #64748B; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px;">Quizzes Completed</div>
        <div style="font-size: 2.8rem; font-weight: 800; color: #10b981;">{user_quizzes}</div>
    </div>
    <div style="width: 1px; height: 60px; background-color: #E2E8F0; display: inline-block;"></div>
    <div style="text-align: center; min-width: 200px;">
        <div style="font-size: 1.05rem; font-weight: 600; color: #64748B; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px;">Standing Status</div>
        <div style="font-size: 1.3rem; font-weight: 700; color: #f97316; margin-top: 10px;">{gap_text}</div>
    </div>
</div>""", unsafe_allow_html=True)
    
    # Leaderboard Table Card
    st.markdown("""<style>
.leaderboard-table {
    width: 100%;
    border-collapse: collapse;
    margin: 10px 0;
    font-size: 1.15rem;
    text-align: left;
}
.leaderboard-table th {
    background-color: #f8fafc;
    color: #475569;
    font-weight: 700;
    padding: 16px 24px;
    border-bottom: 2px solid #e2e8f0;
    text-transform: uppercase;
    font-size: 1.05rem;
    letter-spacing: 0.5px;
}
.leaderboard-table td {
    padding: 18px 24px;
    border-bottom: 1px solid #f1f5f9;
    color: #0f172a;
    font-size: 1.15rem;
}
.leaderboard-table tr {
    transition: background-color 0.2s ease;
}
.leaderboard-table tr:hover {
    background-color: rgba(99, 102, 241, 0.03);
}
.leaderboard-row-active {
    background-color: rgba(99, 102, 241, 0.08) !important;
    border-left: 5px solid #6366f1 !important;
}
.leaderboard-row-active td {
    font-weight: 700 !important;
    color: #4f46e5 !important;
}
.rank-medal {
    font-size: 1.6rem;
    margin-right: 6px;
}
</style>""", unsafe_allow_html=True)

    # Construct Leaderboard Table HTML
    table_rows_html = ""
    for index, u in enumerate(leaderboard_data):
        rank = index + 1
        username = u["username"]
        points = u["total_points"]
        quizzes = u["completed_quizzes"]
        
        # Format last updated timestamp to human readable
        last_updated_str = u["last_updated"]
        try:
            dt = datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
            formatted_date = dt.strftime("%b %d, %I:%M %p")
        except Exception:
            formatted_date = last_updated_str[:16].replace("T", " ")
            
        is_current_user = (u["user_id"] == uid)
        row_class = ' class="leaderboard-row-active"' if is_current_user else ""
        
        # Rank Medal / Icons
        if rank == 1:
            rank_display = '<span class="rank-medal">🥇</span> 1'
        elif rank == 2:
            rank_display = '<span class="rank-medal">🥈</span> 2'
        elif rank == 3:
            rank_display = '<span class="rank-medal">🥉</span> 3'
        else:
            rank_display = f"{rank}"
            
        table_rows_html += f"""<tr{row_class}>
    <td>{rank_display}</td>
    <td>{username} {' (You)' if is_current_user else ''}</td>
    <td><strong>{points}</strong> XP</td>
    <td>{quizzes}</td>
    <td style="color: #64748b; font-size: 1.0rem;">{formatted_date}</td>
</tr>"""
        
    leaderboard_card_html = f"""<div style="background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 24px; padding: 24px; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.03); overflow-x: auto; margin-bottom: 24px;">
    <table class="leaderboard-table">
        <thead>
            <tr>
                <th style="width: 12%;">Rank</th>
                <th style="width: 33%;">User</th>
                <th style="width: 20%;">Total Points</th>
                <th style="width: 15%;">Quizzes</th>
                <th style="width: 20%;">Last Updated</th>
            </tr>
        </thead>
        <tbody>
{table_rows_html}
        </tbody>
    </table>
</div>"""
    st.markdown(leaderboard_card_html, unsafe_allow_html=True)
    
    # Back to home navigation button
    col_back, col_spacer = st.columns([1, 3])
    with col_back:
        if st.button("↩️ Back to Home", use_container_width=True, type="primary", key="lbl_back_home_btn"):
            st.session_state.leaderboard_active = False
            st.rerun()

@st.fragment
def render_left_panel(raw_text, summary_result, api_key, results):
    # Retrieve or initialize chat history for this specific document
    doc_id = results.get('id', 'default_doc')
    chat_history_key = f"chat_history_{doc_id}"
    if chat_history_key not in st.session_state:
        # Load from DB if available in results
        db_history_str = results.get("chat_history", "")
        if db_history_str:
            try:
                st.session_state[chat_history_key] = json.loads(db_history_str)
            except Exception:
                st.session_state[chat_history_key] = []
        else:
            st.session_state[chat_history_key] = []

    # AI Study Assistant Chatbox layout
    # Header Row with Title and Clear Chat Button side-by-side to save space and align cleanly
    title_col, clear_col = st.columns([7, 3], vertical_alignment="center")
    with title_col:
        st.markdown("<h3 style='font-size: 1.6rem; font-weight: 800; color: #0f172a; margin: 0; font-family: \"Poppins\", sans-serif; display: flex; align-items: center; gap: 8px;'>💬 AI Study Assistant</h3>", unsafe_allow_html=True)
    with clear_col:
        if st.button("🧹 Clear", key=f"clear_chat_{doc_id}", use_container_width=True):
            st.session_state[chat_history_key] = []
            if st.session_state.get("user") and results.get('is_loaded_from_db'):
                uid = st.session_state.user.get("uid")
                id_token = st.session_state.user.get("idToken")
                save_chat_history_to_firestore(uid, doc_id, [], id_token)
            st.toast("Chat history cleared!", icon="🧹")
            st.rerun()
    
    st.markdown("<div style='font-size: 0.88rem; color: #6b7280; margin-top: 2px; margin-bottom: 16px;'>Context-aware answers from your notes.</div>", unsafe_allow_html=True)
    
    # Quick Action Buttons
    st.markdown("<div style='margin-bottom: 5px; font-size: 0.8rem; font-weight: 600; color: #4b5563;'>⚡ Quick Prompts:</div>", unsafe_allow_html=True)
    q_col1, q_col2 = st.columns(2)
    with q_col1:
        if st.button("💡 Simpler", key=f"quick_simpler_{doc_id}", use_container_width=True, help="Explain the last concept in simpler terms"):
            st.session_state[f"quick_question_{doc_id}"] = "Can you explain the last concept/topic in simpler terms?"
    with q_col2:
        if st.button("🧪 Example", key=f"quick_example_{doc_id}", use_container_width=True, help="Provide a practical example of the current topic"):
            st.session_state[f"quick_question_{doc_id}"] = "Can you give me a clear, practical example of this concept?"
    
    st.markdown("<hr style='margin: 0.5rem 0; opacity: 0.1;'>", unsafe_allow_html=True)
    
    # Chat Messages Container
    chat_container = st.container(height=450)
    with chat_container:
        if len(st.session_state[chat_history_key]) == 0:
            st.info("👋 Ask anything about these lecture notes!")
        else:
            for msg in st.session_state[chat_history_key]:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])
    
    # Handle Chat Input & Quick Actions
    input_question = st.chat_input("Ask anything about your notes...", key=f"chat_input_val_{doc_id}")
    user_question = None
    
    if input_question:
        user_question = input_question
    elif f"quick_question_{doc_id}" in st.session_state:
        user_question = st.session_state[f"quick_question_{doc_id}"]
        del st.session_state[f"quick_question_{doc_id}"]
    
    if user_question:
        # 1. Immediately render user question inside container
        with chat_container:
            with st.chat_message("user"):
                st.markdown(user_question)
        
        # Append user message
        st.session_state[chat_history_key].append({
            "role": "user",
            "content": user_question
        })
        
        # 2. Immediately render assistant response inside container with spinner
        with chat_container:
            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    # Extract quiz context if active
                    quiz_ctx = ""
                    if st.session_state.get('quiz_data'):
                        quiz_ctx += "\n--- Current/Last Quiz Questions and User Answers ---\n"
                        for i, q_item in enumerate(st.session_state.quiz_data):
                            u_ans = st.session_state.get(f"user_ans_{i}", "Unanswered")
                            c_ans = q_item.get("correct_answer") or q_item.get("answer") or "Unknown"
                            quiz_ctx += f"Question {i+1}: {q_item.get('question')}\n"
                            quiz_ctx += f"User Answer: {u_ans} | Correct Answer: {c_ans}\n"
                    
                    # Call Gemini API
                    from summarizer import generate_chat_response
                    recent_history = st.session_state[chat_history_key][:-1][-10:]
                    
                    response_text = generate_chat_response(
                        ocr_text=raw_text,
                        summary_text=summary_result,
                        chat_history=recent_history,
                        user_question=user_question,
                        api_key=api_key,
                        quiz_context=quiz_ctx
                    )
                    st.markdown(response_text)
                    
        st.session_state[chat_history_key].append({
            "role": "assistant",
            "content": response_text
        })
        
        # Save updated chat history to database
        if st.session_state.get("user") and results.get('is_loaded_from_db'):
            uid = st.session_state.user.get("uid")
            id_token = st.session_state.user.get("idToken")
            save_chat_history_to_firestore(uid, doc_id, st.session_state[chat_history_key], id_token)
        st.rerun()

@st.fragment(run_every=1.0)
def render_quiz_view():
    def get_true_correct(q_dict):
        opts = q_dict.get('options', [])
        ans = q_dict.get('correct_answer') or q_dict.get('answer') or q_dict.get('correct')
        if not ans:
            for k, v in q_dict.items():
                if ('correct' in k.lower() or 'answer' in k.lower()) and isinstance(v, (str, int)):
                    if 'explanation' not in k.lower() and 'trans' not in k.lower():
                        ans = str(v)
                        break
        if not ans:
            return opts[0] if opts else "Unknown"
            
        ans_str = str(ans).strip()
        if ans_str in opts: return ans_str
        
        for o in opts:
            if str(o).strip().lower() == ans_str.lower(): return o
        
        for o in opts:
            o_str = str(o).strip()
            if ans_str.lower() in o_str.lower() or o_str.lower() in ans_str.lower(): return o
            
        if isinstance(ans, str) and len(ans_str) >= 1 and ans_str[0].upper() in ['A', 'B', 'C', 'D']:
            if len(ans_str) == 1 or not ans_str[1].isalpha():
                idx = ord(ans_str[0].upper()) - ord('A')
                if 0 <= idx < len(opts): return opts[idx]
                
        if ans_str.isdigit() and 0 <= int(ans_str) < len(opts):
            return opts[int(ans_str)]
            
        return ans_str

    st.markdown("<br>", unsafe_allow_html=True)
    
    # Custom CSS for the quiz view
    st.markdown("""
        <style>
        /* Make radio text a bit larger and spaced */
        div.stRadio > div[role="radiogroup"] > label {
            background-color: #ffffff;
            padding: 1rem 1.5rem;
            border-radius: 12px;
            border: 1px solid #cbd5e1;
            margin-bottom: 0.8rem;
            transition: all 0.2s ease;
            cursor: pointer;
            box-shadow: 0 2px 4px rgba(0,0,0,0.02);
            width: 100%;
            box-sizing: border-box;
        }
        
        /* Hover state */
        div.stRadio > div[role="radiogroup"] > label:hover {
            border-color: #a8b3cf;
            background-color: #f9fafb;
        }
        
        /* Selected state using :has() */
        div.stRadio > div[role="radiogroup"] > label:has(input:checked) {
            border-color: #6366f1;
            background-color: rgba(99, 102, 241, 0.08);
            box-shadow: 0 0 0 1px #6366f1;
        }
        
        /* Darken radio circle */
        div.stRadio > div[role="radiogroup"] > label div[data-baseweb="radio"] > div:first-child {
            border-color: #94a3b8 !important;
            border-width: 2px !important;
            background-color: #ffffff !important;
        }
        div.stRadio > div[role="radiogroup"] > label:has(input:checked) div[data-baseweb="radio"] > div:first-child {
            border-color: #6366f1 !important;
        }
        
        /* Disabled radio options style */
        div.stRadio > div[role="radiogroup"] > label:has(input:disabled) {
            cursor: not-allowed;
            opacity: 0.85;
            background-color: #f8fafc;
        }
        
        /* Custom styled small buttons inside question navigator */
        .st-key-quiz_nav_container button {
            border-radius: 8px !important;
            padding: 4px 0 !important;
            font-size: 0.85rem !important;
            font-weight: 700 !important;
            min-height: auto !important;
            height: 36px !important;
        }

        /* Quiz View Primary Buttons */
        button[data-testid="baseButton-primary"], button[data-testid="stBaseButton-primary"] {
            background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%) !important;
            color: #ffffff !important;
            border: none !important;
            box-shadow: 0 4px 12px rgba(99, 102, 241, 0.2) !important;
            font-weight: 700 !important;
            border-radius: 10px !important;
            transition: all 0.2s ease !important;
        }
        button[data-testid="baseButton-primary"] *, button[data-testid="stBaseButton-primary"] * {
            color: #ffffff !important;
            font-weight: 700 !important;
        }
        button[data-testid="baseButton-primary"]:hover, button[data-testid="stBaseButton-primary"]:hover {
            background: linear-gradient(135deg, #4f46e5 0%, #4338ca 100%) !important;
            box-shadow: 0 6px 16px rgba(99, 102, 241, 0.35) !important;
            transform: translateY(-1px);
        }
        
        /* Quiz View Secondary Buttons */
        button[data-testid="baseButton-secondary"], button[data-testid="stBaseButton-secondary"] {
            background-color: #f8fafc !important;
            color: #475569 !important;
            border: 1px solid #e2e8f0 !important;
            font-weight: 600 !important;
            border-radius: 10px !important;
            transition: all 0.2s ease !important;
            box-shadow: 0 2px 4px rgba(0,0,0,0.02) !important;
        }
        button[data-testid="baseButton-secondary"]:hover, button[data-testid="stBaseButton-secondary"]:hover {
            background-color: #f1f5f9 !important;
            color: #0f172a !important;
            border-color: #cbd5e1 !important;
            transform: translateY(-1px);
        }

        /* Custom gradient progress bar */
        div[data-testid="stProgress"] > div > div > div > div {
            background-image: linear-gradient(90deg, #6366f1 0%, #8b5cf6 100%) !important;
        }
        </style>
    """, unsafe_allow_html=True)

    # Check user context
    user_info = st.session_state.get("user")
    uid = user_info.get("uid") if user_info else None
    id_token = user_info.get("idToken") if user_info else None

    # Retrieve parameters
    review_mode = st.session_state.get('review_mode', False)
    is_retry = st.session_state.get('is_retry', False)
    parent_attempt_id = st.session_state.get('parent_attempt_id', "")
    difficulty = st.session_state.get('quiz_difficulty', "Medium")
    time_limit_minutes = st.session_state.get('quiz_time_limit_minutes', 0)
    quiz_data = st.session_state.quiz_data
    total_q = len(quiz_data)

    # Check for timer limit
    timer_expired = False
    time_display_str = ""
    if time_limit_minutes > 0 and st.session_state.get('quiz_timer_start') and not review_mode and not st.session_state.get('quiz_finished', False):
        elapsed = time.time() - st.session_state.quiz_timer_start
        remaining = max(0, time_limit_minutes * 60 - elapsed)
        
        if remaining <= 0:
            timer_expired = True
        else:
            rem_mins = int(remaining // 60)
            rem_secs = int(remaining % 60)
            time_display_str = f"⏳ Timer: {rem_mins:02d}:{rem_secs:02d}"

    # Handle Timer Expiration
    if timer_expired:
        # Auto-submit all answered questions up to now
        for i in range(total_q):
            radio_k = f"radio_q_{i}"
            if f"user_ans_{i}" not in st.session_state:
                if st.session_state.get(radio_k) is not None:
                    st.session_state[f'user_ans_{i}'] = st.session_state[radio_k]
                else:
                    st.session_state[f'user_ans_{i}'] = "" # unanswered
            st.session_state[f'q_submitted_{i}'] = True
            
        st.session_state.quiz_finished = True
        st.toast("⌛ Time limit reached! Automatically submitting quiz.", icon="⚠️")
        st.rerun()

    # --- COMPLETION SCREEN ---
    if st.session_state.get('quiz_finished', False):
        spacer1, main_quiz_col, spacer2 = st.columns([1, 6, 1])
        with main_quiz_col:
            st.markdown("<div style='text-align: center;'>", unsafe_allow_html=True)
            st.title("🏆 Quiz Completed!")
            st.markdown("</div>", unsafe_allow_html=True)
            
            score = sum(1 for i, q in enumerate(quiz_data) if st.session_state.get(f'user_ans_{i}') == get_true_correct(q))
            
            # 1. Process Database Save and Progression (Once per quiz completion)
            if not st.session_state.get('quiz_attempt_saved', False):
                # Calculate XP base and scaling multipliers
                diff_multipliers = {"Easy": 1.0, "Medium": 1.5, "Hard": 2.0}
                mult = diff_multipliers.get(difficulty, 1.5)
                
                xp_earned = int(score * 10 * mult)
                # Perfect score bonus
                if score == total_q:
                    xp_earned += 50
                
                time_taken = int(time.time() - st.session_state.quiz_timer_start) if st.session_state.get('quiz_timer_start') else 0
                
                # Determine Badge unlocks
                badge_to_unlock = None
                if is_retry and score == total_q:
                    badge_to_unlock = "persistence"
                elif time_taken <= 120 and score >= 8 and not is_retry:
                    badge_to_unlock = "speed_demon"
                elif score == total_q and difficulty in ("Medium", "Hard"):
                    badge_to_unlock = "perfectionist"
                else:
                    badge_to_unlock = "first_steps"
                    
                # Compile document history answers
                db_answers = []
                for i, q_item in enumerate(quiz_data):
                    user_ans = st.session_state.get(f'user_ans_{i}', "")
                    correct_ans = get_true_correct(q_item)
                    db_answers.append({
                        "question": q_item.get("question", ""),
                        "options": q_item.get("options", []),
                        "user_answer": user_ans,
                        "correct_answer": correct_ans,
                        "is_correct": (user_ans == correct_ans),
                        "topic_tag": q_item.get("topic_tag", "General"),
                        "explanation": q_item.get("explanation", "")
                    })
                
                attempt_data = {
                    "attempt_id": f"attempt_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    "parent_attempt_id": parent_attempt_id,
                    "date": datetime.now().isoformat() + "Z",
                    "topic": st.session_state.ocr_results.get("filename", "Direct Upload") if 'ocr_results' in st.session_state else "General",
                    "difficulty": difficulty,
                    "score": score,
                    "total_questions": total_q,
                    "time_taken_seconds": time_taken,
                    "time_limit_minutes": time_limit_minutes,
                    "xp_earned": xp_earned,
                    "is_retry": is_retry,
                    "answers": db_answers
                }
                
                if uid:
                    # Save attempt
                    save_quiz_attempt(uid, id_token, attempt_data)
                    # Update XP and Level
                    update_user_xp_level(uid, id_token, xp_earned, badge_to_unlock, increment_quizzes=True)
                else:
                    # Guest user: save in local session state
                    if 'guest_quiz_attempts' not in st.session_state:
                        st.session_state.guest_quiz_attempts = []
                    st.session_state.guest_quiz_attempts.append(attempt_data)
                
                st.session_state.quiz_attempt_saved = True
                st.session_state.xp_earned_this_run = xp_earned
                st.session_state.badge_unlocked_this_run = badge_to_unlock
                
            with st.container(border=True):
                st.markdown(f"<h2 style='text-align: center; color: #4338ca;'>Your Final Score: {score} / {total_q}</h2>", unsafe_allow_html=True)
                st.progress(score / total_q)
                
                # Show XP and Level up notification
                if uid and st.session_state.get('quiz_attempt_saved', False):
                    xp_earned = st.session_state.get('xp_earned_this_run', 0)
                    st.markdown(f"<div style='text-align: center; font-weight: 700; color: #8b5cf6; margin-bottom: 15px;'>✨ + {xp_earned} XP Earned! Check your level up in the dashboard.</div>", unsafe_allow_html=True)
                
                st.markdown("<br>", unsafe_allow_html=True)
                if score == total_q:
                    st.balloons()
                    st.success("Perfect score! Excellent understanding of the document.", icon="🌟")
                elif score >= total_q * 0.7:
                    st.info("Great effort! You have a solid understanding.", icon="👍")
                else:
                    st.warning("You might want to review the document again.", icon="📖")
                
                # Question Performance Breakdown List
                st.markdown("<hr style='border: 0; border-top: 1px solid #e2e8f0; margin: 20px 0;'>", unsafe_allow_html=True)
                st.markdown("<h4 style='color: #0f172a; margin-bottom: 15px;'>📊 Question Performance Summary</h4>", unsafe_allow_html=True)
                for i, q_item in enumerate(quiz_data):
                    user_ans = st.session_state.get(f'user_ans_{i}')
                    correct_ans = get_true_correct(q_item)
                    is_correct = (user_ans == correct_ans)
                    
                    status_emoji = "✅ Correct" if is_correct else "❌ Incorrect"
                    status_color = "#10b981" if is_correct else "#ef4444"
                    bg_color = "rgba(16, 185, 129, 0.04)" if is_correct else "rgba(239, 68, 68, 0.04)"
                    
                    q_title = q_item.get('question', '')
                    if len(q_title) > 75:
                        q_title = q_title[:72] + "..."
                        
                    st.markdown(f"""
                        <div style='background-color: {bg_color}; padding: 12px 16px; border-radius: 10px; border-left: 4px solid {status_color}; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;'>
                            <div style='font-size: 0.88rem; color: #334155; font-weight: 500;'>Q{i+1}: {q_title}</div>
                            <div style='font-size: 0.85rem; font-weight: bold; color: {status_color};'>{status_emoji}</div>
                        </div>
                    """, unsafe_allow_html=True)
                
                st.markdown("<br>", unsafe_allow_html=True)
                
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("⬅️ Return to Document", use_container_width=True, key="ret_doc_final_btn"):
                        st.session_state.quiz_mode_active = False
                        st.session_state.quiz_finished = False
                        st.session_state.quiz_data = None
                        st.rerun()
                with col_b:
                    if st.button("Review Answers 🔍", type="primary", use_container_width=True, key="review_final_btn"):
                        st.session_state.quiz_finished = False
                        st.session_state.review_mode = True
                        st.session_state.current_q_index = 0
        return

    # --- ACTIVE QUIZ QUESTION SCREEN ---
    spacer1, main_quiz_col, spacer2 = st.columns([1, 6, 1])
    
    with main_quiz_col:
        title_str = "🔍 Review Mode" if review_mode else ("💪 Retry wrong questions" if is_retry else "📝 Knowledge Quiz")
        st.markdown(f"<h1 style='text-align: center; color: #1e293b; margin-bottom: 0;'>{title_str}</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: #64748b; margin-bottom: 2rem;'>Test your understanding of the document</p>", unsafe_allow_html=True)

        idx = st.session_state.get('current_q_index', 0)
        
        t_col1, t_col2 = st.columns([4, 1])
        with t_col1:
            timer_html = f"<span style='color: #ef4444; font-weight: 700; margin-left: 15px;'>{time_display_str}</span>" if time_display_str else ""
            st.markdown(f"<div style='color: #6b7280; font-weight: 600; font-size: 0.95rem; margin-top: 0.4rem; margin-bottom: 0.5rem;'>Question {idx + 1} of {total_q} {timer_html}</div>", unsafe_allow_html=True)
        with t_col2:
            show_trans = st.toggle("🌐 Translate", key="quiz_translate_toggle")

        st.progress((idx + 1) / total_q)
        
        # Horizontal Question Tracker Grid
        with st.container(key="quiz_nav_container"):
            nav_cols = st.columns(total_q)
            for i in range(total_q):
                with nav_cols[i]:
                    is_curr = (i == idx)
                    is_sub = st.session_state.get(f'q_submitted_{i}', False) or review_mode
                    
                    if is_curr:
                        btn_label = f"🎯 {i+1}"
                        btn_type = "primary"
                    else:
                        btn_type = "secondary"
                        if is_sub:
                            u_ans = st.session_state.get(f'user_ans_{i}')
                            c_ans = get_true_correct(quiz_data[i])
                            if u_ans == c_ans:
                                btn_label = f"✅ {i+1}"
                            else:
                                btn_label = f"❌ {i+1}"
                        else:
                            btn_label = f"📄 {i+1}"
                    
                    if st.button(btn_label, key=f"nav_q_{i}", type=btn_type, use_container_width=True):
                        st.session_state.current_q_index = i
        
        with st.container(border=True):
            q = quiz_data[idx]
            question_text = q.get('question_trans', q.get('question', '')) if show_trans else q.get('question', '')
            
            # Show topic tag inside card
            q_topic = q.get('topic_tag', 'General')
            st.markdown(f"<span style='background-color: #f1f5f9; color: #475569; padding: 2px 8px; border-radius: 4px; font-size: 0.72rem; font-weight: 700;'>🏷️ {q_topic}</span>", unsafe_allow_html=True)
            st.markdown(f"<h3 style='margin-top: 8px; line-height: 1.4;'>{question_text}</h3>", unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)
            
            is_submitted = st.session_state.get(f'q_submitted_{idx}', False) or review_mode
            radio_key = f"radio_q_{idx}"
            
            options_en = q.get('options', [])
            options_trans = q.get('options_trans', [])
            
            display_dict = {}
            for i, opt in enumerate(options_en):
                if show_trans and i < len(options_trans):
                    display_dict[opt] = options_trans[i]
                else:
                    display_dict[opt] = opt
            
            # Format function for highlighting options after submission
            if is_submitted:
                correct_ans = get_true_correct(q)
                user_ans = st.session_state.get(f'user_ans_{idx}', "")
                def format_option(x):
                    base_text = display_dict.get(x, x)
                    if x == correct_ans:
                        return f"✅ :green[**{base_text}** (Correct Answer)]"
                    elif x == user_ans:
                        return f"❌ :red[**{base_text}** (Your Answer - Incorrect)]"
                    return f"⚪ :gray[{base_text}]"
            else:
                def format_option(x):
                    return display_dict.get(x, x)
            
            st.radio(
                "Options", 
                options_en, 
                format_func=format_option,
                key=radio_key,
                index=None,
                label_visibility="collapsed",
                disabled=is_submitted
            )
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            if is_submitted:
                correct_ans = get_true_correct(q)
                user_ans = st.session_state.get(f'user_ans_{idx}')
                
                feedback_correct = "✨ Correct / 正解 / Betul" if show_trans else "Correct! Outstanding job."
                user_ans_disp = display_dict.get(user_ans, user_ans)
                correct_ans_disp = display_dict.get(correct_ans, correct_ans)
                feedback_incorrect = f"❌ **Incorrect**  \nYour answer: {user_ans_disp}  \nCorrect answer: {correct_ans_disp}" if show_trans else f"**Incorrect.**  \nYour answer: {user_ans_disp}  \nCorrect answer: {correct_ans_disp}"
                
                if user_ans == correct_ans:
                    st.success(feedback_correct, icon="✅")
                else:
                    st.error(feedback_incorrect, icon="❌")
                
                explanation_str = q.get('explanation_trans', q.get('explanation', '')) if show_trans else q.get('explanation', '')
                detail_label = "**Explanation / 详细解释：**\n" if show_trans else "**Detailed Explanation:**\n"
                
                st.info(f"{detail_label}{explanation_str}")

        st.markdown("<br>", unsafe_allow_html=True)
        nav_cols = st.columns(4)
        
        with nav_cols[0]:
            exit_label = "🚪 Exit Review" if review_mode else "🚪 Exit Quiz"
            if st.button(exit_label, use_container_width=True, key="exit_quiz_action_btn"):
                st.session_state.quiz_mode_active = False
                st.session_state.review_mode = False
                st.session_state.quiz_data = None
                st.session_state.is_retry = False
                st.session_state.parent_attempt_id = ""
                st.session_state.quiz_attempt_saved = False
                st.rerun()
                
        with nav_cols[1]:
            if idx > 0:
                if st.button("⬅️ Previous", use_container_width=True, key="prev_quiz_action_btn"):
                    st.session_state.current_q_index -= 1
                    
        with nav_cols[2]:
            if not is_submitted and not review_mode:
                if st.button("Submit Answer ✓", type="primary", use_container_width=True, key="submit_answer_action_btn"):
                    if st.session_state.get(radio_key) is None:
                        st.warning("Please select an answer first.")
                    else:
                        st.session_state[f'user_ans_{idx}'] = st.session_state[radio_key]
                        st.session_state[f'q_submitted_{idx}'] = True
                        
        with nav_cols[3]:
            # Navigate next or complete
            if is_submitted or review_mode: 
                if idx < total_q - 1:
                    if st.button("Next ➡️", type="primary", use_container_width=True, key="next_quiz_action_btn"):
                        st.session_state.current_q_index += 1
                else:
                    finish_label = "Finish Review" if review_mode else "Finish Quiz 🏆"
                    if st.button(finish_label, type="primary", use_container_width=True, key="finish_quiz_action_btn"):
                        if review_mode:
                            st.session_state.quiz_mode_active = False
                            st.session_state.review_mode = False
                            st.session_state.quiz_data = None
                            st.rerun()
                        else:
                            st.session_state.quiz_finished = True
                            st.session_state.quiz_attempt_saved = False # reset save flag
                            st.rerun()

def copy_to_clipboard(text, label="Copy"):
    """Creates a small HTML button to copy text to the clipboard"""
    escaped_text = json.dumps(text) # Safely escape for JS
    button_id = f"copy-btn-{abs(hash(label + text[:20]))}" # Ensure positive ID for CSS
    
    # Check if the label already starts with an emoji/symbol to avoid double-prepending
    has_emoji = any(ord(char) > 127 for char in label[:2])
    emoji_html = "" if has_emoji else '<span style="font-size: 0.95rem;">📋</span> '
    
    html_code = f"""
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            html, body {{
                margin: 0;
                padding: 0;
                background-color: transparent !important;
                background: transparent !important;
                overflow: hidden;
                -webkit-text-size-adjust: 100% !important;
                text-size-adjust: 100% !important;
                display: flex !important;
                justify-content: flex-end !important;
                align-items: center !important;
                height: 100% !important;
                width: 100% !important;
            }}
            #{button_id} {{
                background-color: rgba(99, 102, 241, 0.05) !important;
                color: #6366f1 !important;
                border: 1px solid rgba(99, 102, 241, 0.25) !important;
                border-radius: 10px !important;
                padding: 0 16px !important;
                height: 38px !important;
                font-size: 0.875rem !important;
                font-weight: 600 !important;
                cursor: pointer !important;
                transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
                display: inline-flex !important;
                align-items: center !important;
                justify-content: center !important;
                gap: 8px !important;
                margin: 0 !important;
                font-family: 'Inter', sans-serif !important;
                box-shadow: 0 2px 4px rgba(99, 102, 241, 0.02) !important;
                white-space: nowrap !important;
                width: auto !important;
                box-sizing: border-box !important;
                -webkit-text-size-adjust: 100% !important;
                text-size-adjust: 100% !important;
            }}
            #{button_id}:hover {{
                background-color: #6366f1 !important;
                color: white !important;
                border-color: #6366f1 !important;
                box-shadow: 0 6px 16px rgba(99, 102, 241, 0.22) !important;
                transform: translateY(-1px) !important;
            }}
            #{button_id}:active {{
                transform: translateY(0) !important;
                box-shadow: 0 2px 4px rgba(99, 102, 241, 0.1) !important;
            }}
        </style>
        <button id="{button_id}">
            {emoji_html}{label}
        </button>
        <script>
            document.getElementById('{button_id}').onclick = function() {{
                const text = {escaped_text};
                navigator.clipboard.writeText(text).then(() => {{
                    const originalContent = this.innerHTML;
                    this.innerHTML = '<span style="font-size: 0.95rem;">✅</span> Copied!';
                    this.style.backgroundColor = '#6366f1';
                    this.style.color = 'white';
                    setTimeout(() => {{
                        this.innerHTML = originalContent;
                        this.style.backgroundColor = 'rgba(99, 102, 241, 0.05)';
                        this.style.color = '#6366f1';
                    }}, 2000);
                }});
            }};
        </script>
    """
    components.html(html_code, height=44)

def main():

    # Initialize session state for auth
    if 'user' not in st.session_state:
        st.session_state.user = None
    if 'logout_request' not in st.session_state:
        st.session_state.logout_request = False

    user_name = "User"
    if st.session_state.user is not None:
        user_info = st.session_state.user
        user_name = user_info.get('name', 'User') if isinstance(user_info, dict) else 'User'
        user_email = user_info.get('email', '') if isinstance(user_info, dict) else 'User'
        
        if user_name and user_name == user_email and '@' in user_email:
            user_name = user_email.split('@')[0]

        # Initialize user profile details with owner UID check to auto-detect account changes
        current_uid = user_info.get("uid")
        cached_profile = st.session_state.get("user_profile")
        cached_uid = cached_profile.get("uid") if isinstance(cached_profile, dict) else None
        
        if cached_profile is None or cached_uid != current_uid:
            uid = current_uid
            id_token = user_info.get("idToken")
            profile, err = fetch_user_details(uid, id_token)
            if profile and (profile.get("exists", False) or profile.get("name") or profile.get("phone") or profile.get("role") != "Standard Account" or profile.get("bio") or profile.get("gender") != "Prefer not to say" or profile.get("birth_date") or profile.get("joined_at") or profile.get("avatar")):
                if not profile.get("joined_at"):
                    profile["joined_at"] = datetime.now().strftime("%B %d, %Y")
                profile["uid"] = uid
                st.session_state.user_profile = profile
            else:
                st.session_state.user_profile = {
                    "uid": uid,
                    "name": user_name,
                    "phone": "",
                    "role": "Standard Account",
                    "bio": "",
                    "gender": "Prefer not to say",
                    "birth_date": "",
                    "joined_at": datetime.now().strftime("%B %d, %Y"),
                    "avatar": ""
                }

        # Load Gemini API Key from Streamlit Secrets or environment variables
        api_key = st.secrets.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
        
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Poppins:wght@700;800;900&display=swap');
        
        html, body, [class*="css"]  {
            font-family: 'Inter', sans-serif;
            color: #1F2937 !important;
        }
        
        [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li {
            color: #1F2937 !important;
        }
        
        /* Secondary text color styling */
        .hero-subtitle, .profile-role-span, .stCaption, [data-testid="stCaptionContainer"] p, div[data-testid="stCaptionContainer"] {
            color: #6B7280 !important;
        }
        
        /* Style the top navigation horizontal container as a SaaS fixed navbar spanning full width (贯彻头尾) */
        div[data-testid="stHorizontalBlock"]:has(.documind-nav-brand) {
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            right: 0 !important;
            background-color: rgba(15, 23, 42, 0.95) !important;
            backdrop-filter: blur(20px) !important;
            -webkit-backdrop-filter: blur(20px) !important;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1) !important;
            border-top: none !important;
            border-left: none !important;
            border-right: none !important;
            border-radius: 0px !important;
            padding: 12px 3rem !important;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15) !important;
            margin: 0 !important;
            z-index: 999991 !important;
            align-items: center !important;
            box-sizing: border-box !important;
            height: 70px !important;
        }
        
        /* Navbar popover buttons: flat, borderless, and light text */
        div[data-testid="stHorizontalBlock"]:has(.documind-nav-brand) div[data-testid="stPopover"] button {
            background-color: transparent !important;
            border: none !important;
            box-shadow: none !important;
            color: #E2E8F0 !important;
            font-size: 1.05rem !important;
            font-weight: 600 !important;
            padding: 6px 16px !important;
            border-radius: 8px !important;
            transition: all 0.2s ease !important;
            white-space: nowrap !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            gap: 4px !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.documind-nav-brand) div[data-testid="stPopover"] button:hover {
            background-color: rgba(255, 255, 255, 0.08) !important;
            color: #FFFFFF !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.documind-nav-brand) div[data-testid="stPopover"] button *,
        div[data-testid="stHorizontalBlock"]:has(.documind-nav-brand) div[data-testid="stPopover"] button span,
        div[data-testid="stHorizontalBlock"]:has(.documind-nav-brand) div[data-testid="stPopover"] button p {
            color: #E2E8F0 !important;
            font-size: 1.05rem !important;
            font-weight: 600 !important;
            white-space: nowrap !important;
            display: inline !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.documind-nav-brand) div[data-testid="stPopover"] button:hover *,
        div[data-testid="stHorizontalBlock"]:has(.documind-nav-brand) div[data-testid="stPopover"] button:hover span,
        div[data-testid="stHorizontalBlock"]:has(.documind-nav-brand) div[data-testid="stPopover"] button:hover p {
            color: #FFFFFF !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.documind-nav-brand) div[data-testid="stPopover"] button svg {
            color: #E2E8F0 !important;
            fill: currentColor !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.documind-nav-brand) div[data-testid="stPopover"] button:hover svg {
            color: #FFFFFF !important;
        }
        
        /* Make sure the markdown paragraph container inside navigation bar has zero margin/padding to prevent off-centering */
        div[data-testid="stHorizontalBlock"]:has(.documind-nav-brand) p {
            margin: 0 !important;
            padding: 0 !important;
            line-height: 1 !important;
            display: flex !important;
            align-items: center !important;
        }

        /* Force zero margin and padding on all structural wrapper divs in the logo column to guarantee centering */
        div[data-testid="stHorizontalBlock"]:has(.documind-nav-brand) div[data-testid="column"]:first-child div {
            margin: 0 !important;
            padding: 0 !important;
        }

        /* Align navbar components vertically centered */
        div[data-testid="stHorizontalBlock"]:has(.documind-nav-brand) div[data-testid="column"] {
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            height: 100% !important;
            margin: 0 !important;
            padding: 0 !important;
        }
        
        div[data-testid="stHorizontalBlock"]:has(.documind-nav-brand) div[data-testid="column"]:first-child {
            justify-content: flex-start !important;
        }
        
        div[data-testid="stHorizontalBlock"]:has(.documind-nav-brand) div[data-testid="stHorizontalBlock"] {
            align-items: center !important;
            margin: 0 !important;
            height: 100% !important;
            width: 100% !important;
        }
        
        div[data-testid="stHorizontalBlock"]:has(.documind-nav-brand) div[data-testid="stVerticalBlock"] {
            gap: 0px !important;
            margin: 0 !important;
            padding: 0 !important;
            width: 100% !important;
            display: flex !important;
            align-items: center !important;
            height: 100% !important;
            justify-content: center !important;
        }

        /* Centering intermediate Streamlit wrappers */
        div[data-testid="stHorizontalBlock"]:has(.documind-nav-brand) div[data-testid="element-container"],
        div[data-testid="stHorizontalBlock"]:has(.documind-nav-brand) div[class*="element-container"],
        div[data-testid="stHorizontalBlock"]:has(.documind-nav-brand) div[data-testid="stMarkdown"],
        div[data-testid="stHorizontalBlock"]:has(.documind-nav-brand) div[data-testid="stMarkdownContainer"] {
            margin: 0 !important;
            padding: 0 !important;
            display: flex !important;
            align-items: center !important;
            height: 100% !important;
        }
        
        /* Premium Background Gradient (Notion AI / ChatGPT Glow style) */
        [data-testid="stAppViewContainer"] {
            background-color: #F8FAFC !important;
            background-image: 
                radial-gradient(at 0% 0%, rgba(99, 102, 241, 0.04) 0px, transparent 50%),
                radial-gradient(at 100% 0%, rgba(139, 92, 246, 0.04) 0px, transparent 50%) !important;
        }
        
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        
        /* Style the profile container to look like a clean Notion-style profile row */
        div[data-testid="stHorizontalBlock"]:has(.st-key-sidebar_edit_profile_gear_btn) {
            background: transparent !important;
            border: none !important;
            border-radius: 8px !important;
            padding: 4px 8px !important;
            margin-bottom: 12px !important;
            align-items: center !important;
            transition: background 0.2s ease !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.st-key-sidebar_edit_profile_gear_btn):hover {
            background: rgba(0, 0, 0, 0.03) !important;
        }

        /* Remove default margins on paragraph tags inside the profile columns */
        div[data-testid="stHorizontalBlock"]:has(.st-key-sidebar_edit_profile_gear_btn) p {
            margin: 0 !important;
            padding: 0 !important;
            line-height: 1.2 !important;
        }

        /* Remove default margins on markdown containers inside the profile columns */
        div[data-testid="stHorizontalBlock"]:has(.st-key-sidebar_edit_profile_gear_btn) div[data-testid="stMarkdownContainer"] {
            margin: 0 !important;
            padding: 0 !important;
        }

        /* User Profile Card Center Alignment fixes */
        .profile-meta-container {
            display: flex !important;
            align-items: center !important;
            gap: 12px !important;
            min-height: 40px !important;
            height: auto !important;
            width: 100% !important;
        }
        
        .profile-meta-container img {
            display: block !important;
            flex-shrink: 0 !important;
            margin: 0 !important;
            padding: 0 !important;
        }
        
        .profile-text-container {
            display: flex !important;
            flex-direction: column !important;
            justify-content: center !important;
            align-items: flex-start !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
            white-space: nowrap !important;
            line-height: 1.2 !important;
            margin: 0 !important;
            padding: 0 !important;
        }

        .profile-name-span {
            font-weight: 700 !important;
            color: #1f2937 !important;
            font-size: 0.88rem !important;
            line-height: 1.2 !important;
            margin: 0 !important;
            padding: 0 !important;
            display: block !important;
        }

        .profile-role-span {
            font-size: 0.75rem !important;
            color: #6b7280 !important;
            margin-top: 1px !important;
            line-height: 1.2 !important;
            margin-bottom: 0 !important;
            padding: 0 !important;
            display: block !important;
        }

        /* Make the inner column layout expand fully and remove extra spacing */
        div[data-testid="stHorizontalBlock"]:has(.st-key-sidebar_edit_profile_gear_btn) div[data-testid="column"] {
            margin: 0 !important;
            padding: 0 !important;
            display: flex !important;
            align-items: center !important;
        }
        
        /* Gear icon button styling inside the column */
        .st-key-sidebar_edit_profile_gear_btn {
            display: flex !important;
            justify-content: center !important;
            align-items: center !important;
            width: 100% !important;
        }
        .st-key-sidebar_edit_profile_gear_btn button {
            background: transparent !important;
            border: none !important;
            font-size: 1.1rem !important;
            padding: 0 !important;
            height: 28px !important;
            width: 28px !important;
            box-shadow: none !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            transition: all 0.2s ease !important;
        }
        .st-key-sidebar_edit_profile_gear_btn button:hover {
            background: rgba(99, 102, 241, 0.1) !important;
            color: #6366f1 !important;
            border-radius: 50% !important;
            transform: rotate(45deg) !important;
        }
        .st-key-sidebar_edit_profile_gear_btn button:active {
            transform: scale(0.9) rotate(45deg) !important;
        }
        .stDeployButton {display:none;}
        [data-testid="stToolbar"] {visibility: hidden !important;}
        [data-testid="stAppToolbar"] {display: none !important;}

        /* Restyle sidebar with Notion gray background and a clean border-right */
        section[data-testid="stSidebar"] {
            min-width: 280px !important;
            max-width: 280px !important;
            background-color: #F9F9FB !important;
            border-right: 1px solid #E5E7EB !important;
        }
        
        section[data-testid="stSidebar"] > div:first-child {
            width: 280px !important;
            background-color: #F9F9FB !important;
        }

        /* Hide the default header completely to avoid overlapping with fixed header */
        header[data-testid="stHeader"] {
            display: none !important;
        }
        
        /* Hide default Streamlit sidebar collapse button control */
        [data-testid="collapsedControl"] {
            display: none !important;
        }

        /* Style the main container. Make it wide when the top navbar is present, pushing content down to avoid overlap */
        .block-container {
            padding-top: 0.5rem !important;
            padding-bottom: 2rem !important;
            transition: all 0.3s ease !important;
        }
        
        .block-container:has(.documind-nav-brand) {
            max-width: 100% !important;
            padding-left: 3rem !important;
            padding-right: 3rem !important;
            padding-top: 90px !important;
            padding-bottom: 2rem !important;
        }
        
        /* Clean design for primary and secondary action buttons */
        button[data-testid="baseButton-primary"], button[data-testid="stBaseButton-primary"] {
            background: #6366F1 !important;
            color: #FFFFFF !important;
            border-radius: 8px !important;
            border: none !important;
            font-weight: 700 !important;
            box-shadow: 0 4px 12px rgba(99, 102, 241, 0.1) !important;
            transition: all 0.2s ease !important;
        }
        button[data-testid="baseButton-primary"] *, button[data-testid="stBaseButton-primary"] * {
            color: #FFFFFF !important;
            font-weight: 700 !important;
        }
        button[data-testid="baseButton-primary"]:hover, button[data-testid="stBaseButton-primary"]:hover {
            background: #4F46E5 !important;
            box-shadow: 0 6px 16px rgba(99, 102, 241, 0.2) !important;
        }
        button[data-testid="baseButton-secondary"], button[data-testid="stBaseButton-secondary"] {
            background: #FFFFFF !important;
            color: #1F2937 !important;
            border-radius: 8px !important;
            border: 1px solid #E5E7EB !important;
            font-weight: 600 !important;
            transition: all 0.2s ease !important;
            box-shadow: none !important;
        }
        button[data-testid="baseButton-secondary"]:hover, button[data-testid="stBaseButton-secondary"]:hover {
            background: #F8FAFC !important;
            border-color: #A78BFA !important;
            color: #8B5CF6 !important;
        }
        
        /* Generate Quiz Button Explicit Styles */
        div[class*="st-key-generate_quiz_action_btn"] button,
        div[class*="st-key-generate_quiz_action_btn"] button *,
        .st-key-generate_quiz_action_btn button,
        .st-key-generate_quiz_action_btn button * {
            color: #FFFFFF !important;
            font-weight: 700 !important;
        }

        /* Specific button style references have been moved to the bottom of the stylesheet to ensure they cascade and override general button rules */

        /* Upload & Analyze Panel Custom Styling */
        /* Setup Expander Styling (when results exist) */
        div[class*="st-key-setup_expander"] {
            background: linear-gradient(135deg, #EEF2FF 0%, #E0E7FF 100%) !important;
            border: 1px solid rgba(99, 102, 241, 0.2) !important;
            border-radius: 16px !important;
            box-shadow: 0 10px 30px -10px rgba(99, 102, 241, 0.08) !important;
            transition: all 0.3s ease !important;
            overflow: hidden !important;
        }
        div[class*="st-key-setup_expander"]:hover {
            border-color: rgba(99, 102, 241, 0.3) !important;
            box-shadow: 0 15px 35px -8px rgba(99, 102, 241, 0.14) !important;
        }
        div[class*="st-key-setup_expander"] details[open] summary {
            border-bottom: 1px solid rgba(226, 232, 240, 0.6) !important;
        }
        div[class*="st-key-setup_expander"] details summary {
            border-bottom: none !important;
            background-color: transparent !important;
            padding: 14px 20px !important;
            font-size: 1.05rem !important;
            font-weight: 700 !important;
            color: #1e293b !important;
        }
        div[class*="st-key-setup_expander"] details summary:hover {
            background-color: rgba(99, 102, 241, 0.02) !important;
        }
        
        /* Setup Container Styling (when no results exist) */
        div[class*="st-key-setup_container"] {
            background: linear-gradient(135deg, #EEF2FF 0%, #E0E7FF 100%) !important;
            border: 1px solid rgba(99, 102, 241, 0.2) !important;
            border-radius: 16px !important;
            box-shadow: 0 10px 30px -10px rgba(99, 102, 241, 0.08) !important;
            transition: all 0.3s ease !important;
            padding: 24px !important;
        }
        div[class*="st-key-setup_container"]:hover {
            border-color: rgba(99, 102, 241, 0.3) !important;
            box-shadow: 0 15px 35px -8px rgba(99, 102, 241, 0.14) !important;
        }
        
        /* Setup Labels Styling */
        div[class*="st-key-setup_container"] label[data-testid="stWidgetLabel"] p,
        div[class*="st-key-setup_expander"] label[data-testid="stWidgetLabel"] p {
            font-size: 0.98rem !important;
            font-weight: 700 !important;
            color: #1e293b !important;
            margin-bottom: 8px !important;
        }

        /* Premium File Uploader Dropzone Styling */
        div[data-testid="stFileUploader"] {
            padding: 0 !important;
        }
        div[class*="st-key-setup_container"] div[data-testid="stFileUploader"] section[data-testid="stFileUploaderDropzone"],
        div[class*="st-key-setup_expander"] div[data-testid="stFileUploader"] section[data-testid="stFileUploaderDropzone"] {
            background-color: rgba(255, 255, 255, 0.7) !important;
            border: 1.5px dashed rgba(99, 102, 241, 0.25) !important;
            border-radius: 12px !important;
            padding: 16px 20px !important;
            transition: all 0.2s ease !important;
        }
        div[class*="st-key-setup_container"] div[data-testid="stFileUploader"] section[data-testid="stFileUploaderDropzone"]:hover,
        div[class*="st-key-setup_expander"] div[data-testid="stFileUploader"] section[data-testid="stFileUploaderDropzone"]:hover {
            border-color: #6366f1 !important;
            background-color: rgba(255, 255, 255, 0.9) !important;
        }
        div[data-testid="stFileUploader"] section[data-testid="stFileUploaderDropzone"] svg {
            fill: #6366f1 !important;
        }

        /* Sidebar buttons general styling */
        [data-testid="stSidebar"] button {
            text-align: left !important;
            background-color: transparent !important;
            border: none !important;
            color: #4b5563 !important;
            font-size: 0.85rem !important;
            font-weight: 500 !important;
            padding: 6px 12px !important;
            border-radius: 8px !important;
            width: 100% !important;
            display: block !important;
            transition: all 0.15s ease !important;
            box-shadow: none !important;
        }
        [data-testid="stSidebar"] button:hover {
            background-color: #F3F4F6 !important;
            color: #1f2937 !important;
        }
        
        /* Align horizontal blocks vertically centered in the sidebar to prevent trash can misalignment */
        [data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] {
            align-items: center !important;
            gap: 8px !important;
        }
        
        /* Logout button wrapper styling */
        div[class*="st-key-sidebar_logout_button"] button {
            border: 1px solid #E5E7EB !important;
            background-color: #FFFFFF !important;
            color: #EF4444 !important;
            text-align: center !important;
            width: 100% !important;
        }
        div[class*="st-key-sidebar_logout_button"] button:hover {
            background-color: #FEF2F2 !important;
            border-color: #FCA5A5 !important;
            color: #EF4444 !important;
        }
        
        /* Delete buttons wrapper styling - Clean Centered Circle */
        div[class*="st-key-del_doc_"] button {
            color: #9ca3af !important;
            padding: 6px !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            text-align: center !important;
            width: 32px !important;
            height: 32px !important;
            border-radius: 50% !important;
            background-color: transparent !important;
            box-shadow: none !important;
            margin: 0 auto !important;
        }
        div[class*="st-key-del_doc_"] button:hover {
            color: #ef4444 !important;
            background-color: #fef2f2 !important;
        }
        
        /* Force document list load buttons to stay single-line and use ellipsis */
        div[class*="st-key-load_doc_"] button p {
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
            display: block !important;
            width: 100% !important;
        }

        /* Glassmorphic Dropzone styling */
        div[data-testid="stFileUploadDropzone"] {
            background-color: #FFFFFF !important;
            border: 1px dashed #E5E7EB !important;
            border-radius: 12px !important;
            padding: 24px !important;
            transition: all 0.2s ease !important;
        }
        div[data-testid="stFileUploadDropzone"]:hover {
            border-color: #8B5CF6 !important;
            background-color: rgba(139, 92, 246, 0.02) !important;
        }

        /* Metric cards styling override */
        .metric-card {
            background: #FFFFFF !important;
            border: none !important;
            border-radius: 12px !important;
            padding: 16px !important;
            box-shadow: 0 4px 20px -2px rgba(0,0,0,0.03) !important;
        }
        
        /* Headings styling */
        h1, h2, h3, h4, h5, h6 {
            color: #1f2937 !important;
            font-weight: 700 !important;
        }
        
        /* Premium Hero section banner */
        .hero-container {
            background: linear-gradient(135deg, #f5f6ff 0%, #fbf8ff 50%, #fef9ff 100%) !important;
            border: none !important;
            border-radius: 16px !important;
            padding: 32px !important;
            box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.03) !important;
            text-align: center !important;
            margin-bottom: 24px !important;
        }
        
        /* Hero Logo styling to prevent giant sizing and blend white background away */
        .hero-logo {
            height: 96px !important;
            width: auto !important;
            object-fit: contain !important;
            mix-blend-mode: multiply !important;
            transition: transform 0.3s ease !important;
            display: inline-block !important;
        }
        .hero-logo:hover {
            transform: scale(1.05) rotate(-2deg) !important;
        }
        
        .hero-title {
            font-family: 'Poppins', sans-serif;
            font-size: 5.8rem !important;
            font-weight: 900 !important;
            line-height: 1.1 !important;
            letter-spacing: -2px !important;
            background: -webkit-linear-gradient(45deg, #f97316, #e11d48, #9f1239) !important;
            background: linear-gradient(45deg, #f97316, #e11d48, #9f1239) !important;
            -webkit-background-clip: text !important;
            -webkit-text-fill-color: transparent !important;
            margin-bottom: 0.8rem !important;
            margin-top: 0.5rem !important;
            filter: drop-shadow(0px 3px 5px rgba(225, 29, 72, 0.2)) !important;
        }
        .hero-subtitle {
            font-size: 1.05rem !important;
            color: #4b5563 !important;
            font-weight: 600 !important;
            max-width: 650px !important;
            margin: 0 auto 1.5rem auto !important;
            line-height: 1.6 !important;
        }
        .hero-badge {
            background-color: rgba(99, 102, 241, 0.08) !important;
            border: 1px solid rgba(99, 102, 241, 0.15) !important;
            color: #6366F1 !important;
            font-weight: 700 !important;
            font-size: 0.78rem !important;
            letter-spacing: 0.05em !important;
            padding: 4px 12px !important;
            border-radius: 99px !important;
            display: inline-flex !important;
            align-items: center !important;
            gap: 6px !important;
            text-transform: uppercase !important;
        }
        .hero-pills {
            display: flex !important;
            justify-content: center !important;
            gap: 12px !important;
            flex-wrap: wrap !important;
            margin-top: 1.2rem !important;
        }
        .hero-pill {
            background-color: #F8FAFC !important;
            border: 1px solid #E5E7EB !important;
            color: #6B7280 !important;
            padding: 5px 13px !important;
            border-radius: 99px !important;
            font-size: 0.85rem !important;
            font-weight: 600 !important;
            display: flex !important;
            align-items: center !important;
            gap: 6px !important;
            transition: all 0.2s ease !important;
        }
        .hero-pill:hover {
            background-color: #FFFFFF !important;
            border-color: #A78BFA !important;
            color: #6366F1 !important;
            transform: translateY(-1px) !important;
            box-shadow: 0 4px 12px rgba(99, 102, 241, 0.05) !important;
        }
        
        /* Apple segmented control styling for tab list */
        div[data-baseweb="tab-list"] {
            background-color: #F8FAFC !important;
            border: 1px solid #E5E7EB !important;
            padding: 4px !important;
            border-radius: 10px !important;
            display: flex !important;
            gap: 2px !important;
            width: 100% !important;
        }
        div[data-baseweb="tab-list"] button {
            background-color: transparent !important;
            border: none !important;
            border-radius: 8px !important;
            padding: 6px 16px !important;
            font-size: 0.88rem !important;
            font-weight: 500 !important;
            color: #4b5563 !important;
            transition: all 0.2s ease !important;
            height: 34px !important;
            flex: 1 !important;
            justify-content: center !important;
        }
        div[data-baseweb="tab-list"] button[aria-selected="true"] {
            font-weight: 700 !important;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08) !important;
        }
        div[data-baseweb="tab-highlight-line"] {
            display: none !important;
        }

        /* 1. Summary Tab - Solid Royal Blue when selected, soft blue when hovered */
        div[data-baseweb="tab-list"] button:nth-child(1)[aria-selected="true"] {
            background-color: #2563eb !important;
            background: #2563eb !important;
            color: #FFFFFF !important;
            box-shadow: 0 4px 12px rgba(37, 99, 235, 0.2) !important;
        }
        div[data-baseweb="tab-list"] button:nth-child(1)[aria-selected="true"] * {
            color: #FFFFFF !important;
            font-weight: 700 !important;
        }
        div[data-baseweb="tab-list"] button:nth-child(1)[aria-selected="true"]:hover {
            background-color: #1d4ed8 !important;
            background: #1d4ed8 !important;
        }
        div[data-baseweb="tab-list"] button:nth-child(1):not([aria-selected="true"]):hover {
            background-color: rgba(37, 99, 235, 0.06) !important;
            color: #2563eb !important;
        }
        div[data-baseweb="tab-list"] button:nth-child(1):not([aria-selected="true"]):hover * {
            color: #2563eb !important;
        }

        /* 2. Chinese Translation Tab - Solid Violet when selected, soft violet when hovered */
        div[data-baseweb="tab-list"] button:nth-child(2)[aria-selected="true"] {
            background-color: #8b5cf6 !important;
            background: #8b5cf6 !important;
            color: #FFFFFF !important;
            box-shadow: 0 4px 12px rgba(139, 92, 246, 0.2) !important;
        }
        div[data-baseweb="tab-list"] button:nth-child(2)[aria-selected="true"] * {
            color: #FFFFFF !important;
            font-weight: 700 !important;
        }
        div[data-baseweb="tab-list"] button:nth-child(2)[aria-selected="true"]:hover {
            background-color: #7c3aed !important;
            background: #7c3aed !important;
        }
        div[data-baseweb="tab-list"] button:nth-child(2):not([aria-selected="true"]):hover {
            background-color: rgba(139, 92, 246, 0.06) !important;
            color: #8b5cf6 !important;
        }
        div[data-baseweb="tab-list"] button:nth-child(2):not([aria-selected="true"]):hover * {
            color: #8b5cf6 !important;
        }

        /* 3. Mind Map Tab - Solid Emerald Green when selected, soft green when hovered */
        div[data-baseweb="tab-list"] button:nth-child(3)[aria-selected="true"] {
            background-color: #10b981 !important;
            background: #10b981 !important;
            color: #FFFFFF !important;
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.2) !important;
        }
        div[data-baseweb="tab-list"] button:nth-child(3)[aria-selected="true"] * {
            color: #FFFFFF !important;
            font-weight: 700 !important;
        }
        div[data-baseweb="tab-list"] button:nth-child(3)[aria-selected="true"]:hover {
            background-color: #059669 !important;
            background: #059669 !important;
        }
        div[data-baseweb="tab-list"] button:nth-child(3):not([aria-selected="true"]):hover {
            background-color: rgba(16, 185, 129, 0.06) !important;
            color: #10b981 !important;
        }
        div[data-baseweb="tab-list"] button:nth-child(3):not([aria-selected="true"]):hover * {
            color: #10b981 !important;
        }

        /* 4. Quiz Tab - Solid Vibrant Rose when selected, soft rose when hovered */
        div[data-baseweb="tab-list"] button:nth-child(4)[aria-selected="true"] {
            background-color: #f43f5e !important;
            background: #f43f5e !important;
            color: #FFFFFF !important;
            box-shadow: 0 4px 12px rgba(244, 63, 94, 0.2) !important;
        }
        div[data-baseweb="tab-list"] button:nth-child(4)[aria-selected="true"] * {
            color: #FFFFFF !important;
            font-weight: 700 !important;
        }
        div[data-baseweb="tab-list"] button:nth-child(4)[aria-selected="true"]:hover {
            background-color: #e11d48 !important;
            background: #e11d48 !important;
        }
        div[data-baseweb="tab-list"] button:nth-child(4):not([aria-selected="true"]):hover {
            background-color: rgba(244, 63, 94, 0.06) !important;
            color: #f43f5e !important;
        }
        div[data-baseweb="tab-list"] button:nth-child(4):not([aria-selected="true"]):hover * {
            color: #f43f5e !important;
        }
        
        /* Clean white layout with soft shadow, no border, rounded corners for feature cards */
        .feature-card {
            background: #FFFFFF;
            border: none !important;
            border-radius: 12px !important;
            padding: 20px !important;
            box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.03) !important;
            transition: transform 0.2s ease, box-shadow 0.2s ease !important;
            height: 100% !important;
            text-align: center !important;
        }
        .feature-card-ocr {
            background: linear-gradient(135deg, #EFF6FF 0%, #E0F2FE 100%) !important;
            border: 1px solid rgba(59, 130, 246, 0.12) !important;
        }
        .feature-card-ocr:hover {
            transform: translateY(-2px) !important;
            box-shadow: 0 10px 25px -5px rgba(59, 130, 246, 0.15) !important;
        }
        .feature-card-synthesis {
            background: linear-gradient(135deg, #FAF5FF 0%, #F3E8FF 100%) !important;
            border: 1px solid rgba(139, 92, 246, 0.12) !important;
        }
        .feature-card-synthesis:hover {
            transform: translateY(-2px) !important;
            box-shadow: 0 10px 25px -5px rgba(139, 92, 246, 0.15) !important;
        }
        .feature-card-mindmap {
            background: linear-gradient(135deg, #ECFDF5 0%, #D1FAE5 100%) !important;
            border: 1px solid rgba(16, 185, 129, 0.12) !important;
        }
        .feature-card-mindmap:hover {
            transform: translateY(-2px) !important;
            box-shadow: 0 10px 25px -5px rgba(16, 185, 129, 0.15) !important;
        }
        .feature-card-icon {
            font-size: 2.2rem !important;
            margin-bottom: 14px !important;
        }
        .feature-card-title {
            font-size: 1.3rem !important;
            font-weight: 700 !important;
            color: #1F2937 !important;
            margin-bottom: 8px !important;
        }
        .feature-card-desc {
            font-size: 0.98rem !important;
            color: #4B5563 !important;
            font-weight: 600 !important;
            line-height: 1.6 !important;
        }

        /* Glassmorphic Expander styling */
        div[data-testid="stExpander"] {
            background: #FFFFFF !important;
            border: 1px solid #E5E7EB !important;
            border-radius: 12px !important;
            box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.03) !important;
            overflow: hidden !important;
            margin-bottom: 16px !important;
        }
        div[data-testid="stExpander"] details {
            border: none !important;
        }
        div[data-testid="stExpander"] summary {
            background-color: #FFFFFF !important;
            padding: 12px 16px !important;
            font-weight: 600 !important;
            color: #374151 !important;
        }
        div[data-testid="stExpander"] summary:hover {
            background-color: #F9FAFB !important;
        }

        /* Clean chatbot messaging layout */
        [data-testid="stChatMessage"] {
            background-color: transparent !important;
            border: none !important;
            padding: 8px 12px !important;
        }
        [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
            background-color: rgba(99, 102, 241, 0.06) !important;
            border-radius: 12px 12px 0 12px !important;
            border: 1px solid rgba(99, 102, 241, 0.1) !important;
        }
        [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
            background-color: #FFFFFF !important;
            border: 1px solid #E5E7EB !important;
            border-radius: 12px 12px 12px 0 !important;
        }

        /* 3-Column Premium Feature Grid */
        .feature-grid {
            display: grid !important;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)) !important;
            gap: 20px !important;
            margin-bottom: 30px !important;
        }

        /* Segmented control button margins */
        div[data-testid="stSegmentedControl"] {
            background-color: #F8FAFC !important;
            border: 1px solid #E5E7EB !important;
            padding: 4px !important;
            border-radius: 10px !important;
            margin-bottom: 16px !important;
        }
        div[data-testid="stSegmentedControl"] button {
            background-color: transparent !important;
            border: none !important;
            border-radius: 8px !important;
            height: 32px !important;
            font-size: 0.85rem !important;
        }
        div[data-testid="stSegmentedControl"] button[aria-checked="true"] {
            background-color: #FFFFFF !important;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06) !important;
            color: #6366F1 !important;
        }

        /* AI Chatbox Buttons Styling */
        div[class*="st-key-quick_"] button {
            font-size: 0.8rem !important;
            padding: 4px 8px !important;
            min-height: 32px !important;
            height: 32px !important;
            white-space: nowrap !important;
            text-wrap: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
            border: 1px solid #E5E7EB !important;
            background: #FFFFFF !important;
            color: #4b5563 !important;
            border-radius: 6px !important;
            box-shadow: none !important;
        }
        div[class*="st-key-quick_"] button:hover {
            background: #F9FAFB !important;
            border-color: #D1D5DB !important;
            color: #1f2937 !important;
        }
        div[class*="st-key-clear_chat_"] button {
            font-size: 0.8rem !important;
            padding: 4px 8px !important;
            min-height: 32px !important;
            height: 32px !important;
            white-space: nowrap !important;
            text-wrap: nowrap !important;
            border: 1px solid rgba(239, 68, 68, 0.2) !important;
            background: #FFFFFF !important;
            color: #ef4444 !important;
            border-radius: 6px !important;
            box-shadow: none !important;
        }
        div[class*="st-key-clear_chat_"] button:hover {
            background: #FEF2F2 !important;
            border-color: #FCA5A5 !important;
        }

        /* Main Page Clear Results Button - Soft Destructive Red Border on Hover */
        div[data-testid="stContainer"]:has([data-testid="stFileUploadDropzone"]) button[data-testid="baseButton-secondary"]:hover {
            background-color: #fef2f2 !important;
            color: #ef4444 !important;
            border-color: #fca5a5 !important;
        }

        /* ----------------------------------------------------
           SPECIFIC BUTTON OVERRIDES (defined at the bottom to ensure CSS cascade order)
           ---------------------------------------------------- */

        /* 1. "💡 Simpler" Button - Solid Amber Yellow */
        div[class*="st-key-quick_simpler"] button,
        div[class*="st-key-quick-simpler"] button,
        button[aria-label*="Simpler"],
        div[class*="quick_simpler"] button,
        div[class*="quick-simpler"] button {
            background-color: #f59e0b !important;
            background: #f59e0b !important;
            color: #FFFFFF !important;
            border: none !important;
            border-radius: 8px !important;
            font-weight: 700 !important;
            box-shadow: 0 4px 12px rgba(245, 158, 11, 0.15) !important;
            transition: all 0.2s ease !important;
        }
        div[class*="st-key-quick_simpler"] button *,
        div[class*="st-key-quick-simpler"] button *,
        button[aria-label*="Simpler"] *,
        div[class*="quick_simpler"] button *,
        div[class*="quick-simpler"] button * {
            color: #FFFFFF !important;
            font-weight: 700 !important;
            transition: all 0.2s ease !important;
        }
        div[class*="st-key-quick_simpler"] button:hover,
        div[class*="st-key-quick-simpler"] button:hover,
        button[aria-label*="Simpler"]:hover,
        div[class*="quick_simpler"] button:hover,
        div[class*="quick-simpler"] button:hover {
            background-color: #d97706 !important;
            background: #d97706 !important;
            color: #FFFFFF !important;
            box-shadow: 0 6px 16px rgba(245, 158, 11, 0.25) !important;
            transform: translateY(-1px);
        }
        div[class*="st-key-quick_simpler"] button:hover *,
        div[class*="st-key-quick-simpler"] button:hover *,
        button[aria-label*="Simpler"]:hover *,
        div[class*="quick_simpler"] button:hover *,
        div[class*="quick-simpler"] button:hover * {
            color: #FFFFFF !important;
        }

        /* 2. "🧪 Example" Button - Solid Emerald Green */
        div[class*="st-key-quick_example"] button,
        div[class*="st-key-quick-example"] button,
        button[aria-label*="Example"],
        div[class*="quick_example"] button,
        div[class*="quick-example"] button {
            background-color: #10b981 !important;
            background: #10b981 !important;
            color: #FFFFFF !important;
            border: none !important;
            border-radius: 8px !important;
            font-weight: 700 !important;
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.15) !important;
            transition: all 0.2s ease !important;
        }
        div[class*="st-key-quick_example"] button *,
        div[class*="st-key-quick-example"] button *,
        button[aria-label*="Example"] *,
        div[class*="quick_example"] button *,
        div[class*="quick-example"] button * {
            color: #FFFFFF !important;
            font-weight: 700 !important;
            transition: all 0.2s ease !important;
        }
        div[class*="st-key-quick_example"] button:hover,
        div[class*="st-key-quick-example"] button:hover,
        button[aria-label*="Example"]:hover,
        div[class*="quick_example"] button:hover,
        div[class*="quick-example"] button:hover {
            background-color: #059669 !important;
            background: #059669 !important;
            color: #FFFFFF !important;
            box-shadow: 0 6px 16px rgba(16, 185, 129, 0.25) !important;
            transform: translateY(-1px);
        }
        div[class*="st-key-quick_example"] button:hover *,
        div[class*="st-key-quick-example"] button:hover *,
        button[aria-label*="Example"]:hover *,
        div[class*="quick_example"] button:hover *,
        div[class*="quick-example"] button:hover * {
            color: #FFFFFF !important;
        }

        /* 3. "🧹 Clear" Button - Solid Coral Red */
        div[class*="st-key-clear_chat"] button,
        div[class*="st-key-clear-chat"] button,
        button[aria-label*="Clear"],
        div[class*="clear_chat"] button,
        div[class*="clear-chat"] button {
            background-color: #ef4444 !important;
            background: #ef4444 !important;
            color: #FFFFFF !important;
            border: none !important;
            border-radius: 8px !important;
            font-weight: 700 !important;
            box-shadow: 0 4px 12px rgba(239, 68, 68, 0.15) !important;
            transition: all 0.2s ease !important;
        }
        div[class*="st-key-clear_chat"] button *,
        div[class*="st-key-clear-chat"] button *,
        button[aria-label*="Clear"] *,
        div[class*="clear_chat"] button *,
        div[class*="clear-chat"] button * {
            color: #FFFFFF !important;
            font-weight: 700 !important;
            transition: all 0.2s ease !important;
        }
        div[class*="st-key-clear_chat"] button:hover,
        div[class*="st-key-clear-chat"] button:hover,
        button[aria-label*="Clear"]:hover,
        div[class*="clear_chat"] button:hover,
        div[class*="clear-chat"] button:hover {
            background-color: #dc2626 !important;
            background: #dc2626 !important;
            color: #FFFFFF !important;
            box-shadow: 0 6px 16px rgba(239, 68, 68, 0.25) !important;
            transform: translateY(-1px);
        }
        div[class*="st-key-clear_chat"] button:hover *,
        div[class*="st-key-clear-chat"] button:hover *,
        button[aria-label*="Clear"]:hover *,
        div[class*="clear_chat"] button:hover *,
        div[class*="clear-chat"] button:hover * {
            color: #FFFFFF !important;
        }

        /* 4. "📤 Export Document" Button - Indigo */
        div[class*="st-key-export_document"] button,
        div[class*="st-key-export-document"] button,
        button[aria-label*="Export Document"],
        div[class*="export_document_popover"] button,
        div[class*="export-document-popover"] button {
            background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%) !important;
            background-color: #6366f1 !important;
            border: none !important;
            color: #FFFFFF !important;
            font-weight: 700 !important;
            border-radius: 8px !important;
            box-shadow: 0 4px 12px rgba(99, 102, 241, 0.15) !important;
            transition: all 0.2s ease !important;
        }
        div[class*="st-key-export_document"] button *,
        div[class*="st-key-export-document"] button *,
        button[aria-label*="Export Document"] *,
        div[class*="export_document_popover"] button *,
        div[class*="export-document-popover"] button * {
            color: #FFFFFF !important;
            font-weight: 700 !important;
            transition: all 0.2s ease !important;
        }
        div[class*="st-key-export_document"] button:hover,
        div[class*="st-key-export-document"] button:hover,
        button[aria-label*="Export Document"]:hover,
        div[class*="export_document_popover"] button:hover,
        div[class*="export-document-popover"] button:hover {
            background: linear-gradient(135deg, #4f46e5 0%, #4338ca 100%) !important;
            background-color: #4f46e5 !important;
            color: #FFFFFF !important;
            box-shadow: 0 6px 16px rgba(99, 102, 241, 0.25) !important;
            transform: translateY(-1px);
        }
        div[class*="st-key-export_document"] button:hover *,
        div[class*="st-key-export-document"] button:hover *,
        button[aria-label*="Export Document"]:hover *,
        div[class*="export_document_popover"] button:hover *,
        div[class*="export-document-popover"] button:hover * {
            color: #FFFFFF !important;
        }

        /* Force iframe transparency to avoid solid white background boxes on iOS/Safari */
        iframe {
            background-color: transparent !important;
            background: transparent !important;
        }

        /* AI Study Assistant Chatbot Card Container styling */
        div[class*="st-key-chatbot_container"],
        div[data-testid="stBorderedContainer"][class*="st-key-chatbot_container"],
        div[class*="st-key-chatbot_container"] div[data-testid="stBorderedContainer"],
        div[data-testid="column"] div[class*="st-key-chatbot_container"],
        div[data-testid="stHorizontalBlock"] div[data-testid="column"]:last-child div[data-testid="stBorderedContainer"],
        div[data-testid="stHorizontalBlock"] div[data-testid="column"]:last-of-type div[data-testid="stBorderedContainer"] {
            background-color: #FFFFFF !important;
            border: 1px solid #E5E7EB !important;
            border-radius: 16px !important;
            padding: 24px !important;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03) !important;
            margin-bottom: 1.5rem !important;
        }

        /* st.popover body container: Force white background, border and light theme text/contents */
        div[data-testid="stPopoverBody"] {
            background-color: #FFFFFF !important;
            border: 1px solid #E5E7EB !important;
            border-radius: 12px !important;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1) !important;
            padding: 16px 16px 28px 16px !important;
            max-height: 420px !important;
            overflow-y: auto !important;
            -webkit-overflow-scrolling: touch !important;
        }
        div[data-testid="stPopoverBody"] > div,
        div[data-testid="stPopoverBody"] [data-testid="stVerticalBlock"],
        div[data-testid="stPopoverBody"] [data-testid="stVerticalBlockBorderWrapper"],
        div[data-testid="stPopoverBody"] [data-testid="stHorizontalBlock"],
        div[data-testid="stPopoverBody"] [data-testid="column"],
        div[data-testid="stPopoverBody"] [data-testid="element-container"],
        div[data-testid="stPopoverBody"] [class*="element-container"] {
            background-color: transparent !important;
            background: transparent !important;
        }
        div[data-testid="stPopoverBody"] p,
        div[data-testid="stPopoverBody"] span,
        div[data-testid="stPopoverBody"] label,
        div[data-testid="stPopoverBody"] h1,
        div[data-testid="stPopoverBody"] h2,
        div[data-testid="stPopoverBody"] h3,
        div[data-testid="stPopoverBody"] h4,
        div[data-testid="stPopoverBody"] h5,
        div[data-testid="stPopoverBody"] h6,
        div[data-testid="stPopoverBody"] [data-testid="stMarkdownContainer"] {
            color: #1F2937 !important;
        }
        div[data-testid="stPopoverBody"] div[data-testid="stCaptionContainer"] p,
        div[data-testid="stPopoverBody"] div[data-testid="stCaptionContainer"] {
            color: #6B7280 !important;
        }
        /* Buttons inside popover body: keep clean theme integration */
        div[data-testid="stPopoverBody"] button[data-testid="baseButton-secondary"] *,
        div[data-testid="stPopoverBody"] button[data-testid="baseButton-secondary"] span,
        div[data-testid="stPopoverBody"] button[data-testid="baseButton-secondary"] p {
            color: #1F2937 !important;
        }
        div[data-testid="stPopoverBody"] button[data-testid="baseButton-secondary"]:hover *,
        div[data-testid="stPopoverBody"] button[data-testid="baseButton-secondary"]:hover span,
        div[data-testid="stPopoverBody"] button[data-testid="baseButton-secondary"]:hover p {
            color: #8B5CF6 !important;
        }
        div[data-testid="stPopoverBody"] div[class*="st-key-del_doc_"] button {
            color: #9ca3af !important;
        }
        div[data-testid="stPopoverBody"] div[class*="st-key-del_doc_"] button:hover {
            color: #ef4444 !important;
            background-color: #fef2f2 !important;
        }

        /* Global st.selectbox overrides to force premium white styling */
        div[data-testid="stSelectbox"] div[role="button"],
        div[data-testid="stSelectbox"] div[role="combobox"],
        div[data-testid="stSelectbox"] select {
            background-color: #FFFFFF !important;
            color: #1F2937 !important;
            border: 1px solid #E2E8F0 !important;
            border-radius: 10px !important;
        }
        div[data-testid="stSelectbox"] div[role="button"] *,
        div[data-testid="stSelectbox"] div[role="combobox"] *,
        div[data-testid="stSelectbox"] select * {
            color: #1F2937 !important;
        }
        div[data-testid="stSelectbox"] div[role="button"]:focus,
        div[data-testid="stSelectbox"] div[role="combobox"]:focus,
        div[data-testid="stSelectbox"] div[role="button"]:active,
        div[data-testid="stSelectbox"] div[role="combobox"]:active {
            border-color: #6366f1 !important;
            box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1) !important;
        }
        
        /* Selectbox Dropdown overlay menu lists styling */
        div[data-baseweb="popover"] [data-baseweb="menu"],
        div[data-baseweb="popover"] ul[role="listbox"],
        [data-testid="stSelectboxVirtualDropdown"] {
            background-color: #FFFFFF !important;
            background: #FFFFFF !important;
            border: 1px solid #E2E8F0 !important;
            border-radius: 10px !important;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.08) !important;
        }
        div[data-baseweb="popover"] [data-baseweb="menu"] li,
        div[data-baseweb="popover"] ul[role="listbox"] li,
        [data-testid="stSelectboxVirtualDropdown"] li,
        [data-testid="stSelectboxVirtualDropdown"] div[role="option"] {
            background-color: #FFFFFF !important;
            color: #1F2937 !important;
            padding: 8px 16px !important;
            font-size: 0.95rem !important;
        }
        div[data-baseweb="popover"] [data-baseweb="menu"] li *,
        div[data-baseweb="popover"] ul[role="listbox"] li *,
        [data-testid="stSelectboxVirtualDropdown"] li *,
        [data-testid="stSelectboxVirtualDropdown"] div[role="option"] * {
            color: #1F2937 !important;
        }
        
        /* Hover state on dropdown options */
        div[data-baseweb="popover"] [data-baseweb="menu"] li:hover,
        div[data-baseweb="popover"] ul[role="listbox"] li:hover,
        [data-testid="stSelectboxVirtualDropdown"] li:hover,
        [data-testid="stSelectboxVirtualDropdown"] div[role="option"]:hover,
        div[data-baseweb="popover"] [data-baseweb="menu"] li[aria-selected="true"],
        div[data-baseweb="popover"] ul[role="listbox"] li[aria-selected="true"],
        [data-testid="stSelectboxVirtualDropdown"] li[aria-selected="true"] {
            background-color: #F1F5F9 !important;
        }
        div[data-baseweb="popover"] [data-baseweb="menu"] li:hover *,
        div[data-baseweb="popover"] ul[role="listbox"] li:hover *,
        [data-testid="stSelectboxVirtualDropdown"] li:hover *,
        [data-testid="stSelectboxVirtualDropdown"] div[role="option"]:hover *,
        div[data-baseweb="popover"] [data-baseweb="menu"] li[aria-selected="true"] *,
        div[data-baseweb="popover"] ul[role="listbox"] li[aria-selected="true"] *,
        [data-testid="stSelectboxVirtualDropdown"] li[aria-selected="true"] * {
            color: #6366f1 !important;
        }
        </style>
    """, unsafe_allow_html=True)
    
    # API key and settings are handled in the logged-in main flow

    if st.session_state.user is None:
        logo_html = ""
        logo_path = "logo.png"
        if os.path.exists(logo_path):
            with open(logo_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode()
            logo_html = f'<img src="data:image/png;base64,{encoded_string}" style="height: 100px; border-radius: 16px; box-shadow: 0 8px 15px rgba(0,0,0,0.1);">'
            
        # Get current date and time
        now = datetime.now()
        current_datetime = now.strftime("%b %d, %Y • %I:%M %p")
        
        # Show Authentication Component
        banner_html = f"""
            <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@800;900&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
            <style>
                .date-badge-absolute {{
                    position: absolute;
                    top: 20px;
                    right: 24px;
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                    background: rgba(255, 255, 255, 0.6);
                    padding: 6px 14px;
                    border-radius: 20px;
                    border: 1px solid rgba(255, 255, 255, 0.8);
                    color: #4338ca;
                    font-size: 0.85rem;
                    font-weight: 600;
                    backdrop-filter: blur(4px);
                    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
                    z-index: 10;
                }}
                .documind-banner {{
                    position: relative;
                    text-align: center;
                    margin-bottom: 30px;
                    padding: 40px 20px 60px 20px;
                    border-radius: 24px;
                    overflow: hidden;
                    border: 1px solid rgba(255, 255, 255, 0.4);
                    box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
                    font-family: 'Inter', sans-serif;
                    background: linear-gradient(135deg, #e0e7ff 0%, #e9d5ff 50%, #fae8ff 100%);
                }}
                .documind-banner::before {{
                    content: '';
                    position: absolute;
                    bottom: 0; left: 0; right: 0; height: 160px;
                    background: url('data:image/svg+xml;utf8,<svg viewBox="0 0 1440 320" xmlns="http://www.w3.org/2000/svg"><path fill="rgba(255, 255, 255, 0.6)" fill-opacity="1" d="M0,128L48,144C96,160,192,192,288,197.3C384,203,480,181,576,149.3C672,117,768,75,864,80C960,85,1056,139,1152,160C1248,181,1344,171,1392,165.3L1440,160L1440,320L1392,320C1344,320,1248,320,1152,320C1056,320,960,320,864,320C768,320,672,320,576,320C480,320,384,320,288,320C192,320,96,320,48,320L0,320Z"></path></svg>') bottom center / cover no-repeat;
                    z-index: 0;
                }}
                .documind-banner::after {{
                    content: '';
                    position: absolute;
                    bottom: 0; left: 0; right: 0; height: 120px;
                    background: url('data:image/svg+xml;utf8,<svg viewBox="0 0 1440 320" xmlns="http://www.w3.org/2000/svg"><path fill="%23ffffff" fill-opacity="1" d="M0,224L48,213.3C96,203,192,181,288,181.3C384,181,480,203,576,218.7C672,235,768,245,864,213.3C960,181,1056,107,1152,101.3C1248,96,1344,160,1392,192L1440,224L1440,320L1392,320C1344,320,1248,320,1152,320C1056,320,960,320,864,320C768,320,672,320,576,320C480,320,384,320,288,320C192,320,96,320,48,320L0,320Z"></path></svg>') bottom center / cover no-repeat;
                    z-index: 0;
                }}
                .banner-content {{
                    position: relative;
                    z-index: 1;
                }}
                .feature-tags {{
                    display: flex;
                    justify-content: center;
                    gap: 12px;
                    margin-top: 20px;
                    flex-wrap: wrap;
                }}
                .feature-tag {{
                    background: rgba(255, 255, 255, 0.5);
                    border: 1px solid rgba(255, 255, 255, 0.8);
                    padding: 6px 14px;
                    border-radius: 20px;
                    font-size: 0.85rem;
                    color: #4f46e5;
                    font-weight: 600;
                    backdrop-filter: blur(4px);
                    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.02);
                    display: flex;
                    align-items: center;
                    gap: 6px;
                }}
            </style>
            
            <div class="documind-banner">
                <div class="date-badge-absolute">
                    <span>🕒</span> {current_datetime}
                </div>
                <div class="banner-content">
                    <div style="display: flex; align-items: center; justify-content: center; gap: 24px; margin-bottom: 15px;">
                        {logo_html}
                        <h1 style="
                            font-family: 'Poppins', sans-serif;
                            font-size: 5.5rem; 
                            font-weight: 900; 
                            margin: 0;
                            background: -webkit-linear-gradient(45deg, #f97316, #e11d48, #9f1239);
                            -webkit-background-clip: text;
                            -webkit-text-fill-color: transparent;
                            line-height: 1;
                            letter-spacing: -2px;
                            filter: drop-shadow(0px 4px 6px rgba(225, 29, 72, 0.4)) drop-shadow(0px 10px 15px rgba(249, 115, 22, 0.2));
                            transform: translateZ(0);
                        ">DocuMind</h1>
                    </div>
                    <p style="color: #4338ca; font-size: 1.25rem; margin: 0; margin-bottom: 10px; font-weight: 600; letter-spacing: 0.5px; text-align: center;">Smart Document Summarization</p>
                    <div class="feature-tags"><div class="feature-tag"><span>👁️</span> OCR Extraction</div><div class="feature-tag"><span>🧠</span> AI Summarization</div><div class="feature-tag"><span>⚡</span> Fast & Accurate</div></div>
                </div>
            </div>
        """
        
        # Load the Firebase Auth Component
        try:
            firebase_auth = components.declare_component("firebase_auth", path="auth_component_dir")
            # Pass logout status to component
            user_data = firebase_auth(logout=st.session_state.logout_request, banner_html=banner_html, key="auth_session")
            
            if user_data is not None:
                if user_data == "LOGOUT_DONE":
                    if st.session_state.get('logout_request', False):
                        st.session_state.logout_request = False
                        st.session_state.user = None
                        st.session_state.user_profile = None
                        if 'ocr_results' in st.session_state:
                            del st.session_state.ocr_results
                        if 'quiz_data' in st.session_state:
                            del st.session_state.quiz_data
                        st.session_state.quiz_mode_active = False
                        st.session_state.edit_profile_active = False
                        st.session_state.quiz_finished = False
                        st.session_state.quiz_submitted = False
                        st.session_state.guest_quiz_attempts = []
                        st.rerun()
                else:
                    # user_data is a dict containing {uid, email, name} received from Custom Component
                    st.session_state.user = user_data
                    st.session_state.logout_request = False
                    
                    # Sync any guest quiz attempts to the new user account database
                    guest_attempts = st.session_state.get("guest_quiz_attempts", [])
                    if guest_attempts:
                        g_uid = user_data.get("uid")
                        g_token = user_data.get("idToken")
                        for g_att in guest_attempts:
                            save_quiz_attempt(g_uid, g_token, g_att)
                            # Award XP
                            update_user_xp_level(g_uid, g_token, g_att.get("xp_earned", 0), increment_quizzes=True)
                        st.session_state.guest_quiz_attempts = []
                        st.toast("⚡ Guest quiz attempts synchronized to your account!", icon="🚀")
                        time.sleep(1)
                        
                    st.rerun() # Refresh to show main app
                 
        except Exception as e:
            st.error(f"Error loading authentication component: {e}")
        
        return # Stop execution of the rest of the app until logged in

    if st.session_state.get('edit_profile_active', False):
        render_edit_profile_view()
        return

    if st.session_state.get('leaderboard_active', False):
        render_leaderboard_view()
        return

    if st.session_state.get('quiz_mode_active', False):
        render_quiz_view()
        return

    # ------------------ Main Interface ------------------
    # 开始在后台静默加载模型（带延迟以保障过渡动画和页面极速渲染完毕）
    initialize_models()
    # ------------------ Top Navigation Bar (SaaS Header) ------------------
    nav_col1, nav_col2 = st.columns([5.5, 4.5])
    with nav_col1:
        st.markdown("""
            <div class="documind-nav-brand" style="display: flex; align-items: center; gap: 10px;">
                <span style="font-size: 1.6rem; background: linear-gradient(45deg, #f97316, #e11d48, #9f1239); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: 800; font-family: 'Poppins', sans-serif;">DocuMind</span>
                <span style="background: rgba(99, 102, 241, 0.25); color: #818CF8; font-size: 0.72rem; font-weight: 700; padding: 2px 8px; border-radius: 99px;">PRO</span>
            </div>
        """, unsafe_allow_html=True)
        
    with nav_col2:
        p_col1, p_col2, p_col3 = st.columns([1, 1, 1])
        
        # Access user variables from outer scope
        uid = user_info.get("uid") if user_info else None
        id_token = user_info.get("idToken") if user_info else None
        
        with p_col1:
            with st.popover("📂 Documents", use_container_width=True):
                st.markdown("<h4 style='font-size: 0.95rem; font-weight: 700; color: #1f2937; margin-bottom: 12px;'>📚 Saved Summaries</h4>", unsafe_allow_html=True)
                if not uid:
                    st.caption("Log in to view saved summaries.")
                else:
                    saved_docs, err = fetch_saved_summaries(uid, id_token)
                    if err:
                        st.caption(f"⚠️ Failed to load history: {err[:60]}...")
                    elif not saved_docs:
                        st.caption("No saved summaries yet.")
                    else:
                        active_doc_id = st.session_state.ocr_results.get('id') if 'ocr_results' in st.session_state else None
                        for doc in saved_docs:
                            doc_title = doc.get("title", "Untitled")
                            doc_id = doc.get("id")
                            display_title = doc_title if len(doc_title) <= 22 else doc_title[:20] + "..."
                            
                            is_active = (active_doc_id == doc_id)
                            prefix = "🟢 " if is_active else "📄 "
                            
                            h_col1, h_col2 = st.columns([5, 1.2])
                            with h_col1:
                                if st.button(f"{prefix}{display_title}", key=f"load_doc_{doc_id}", use_container_width=True, help=doc_title):
                                    st.session_state.ocr_results = {
                                        'id': doc_id,
                                        'raw_text': doc.get("raw_text", "Loaded from cloud account database."),
                                        'summary': doc.get("summary", ""),
                                        'translation': doc.get("translation", ""),
                                        'mindmap_eng': doc.get("mindmap_eng", ""),
                                        'mindmap_trans': doc.get("mindmap_trans", ""),
                                        'time': 0.0,
                                        'lang': doc.get("language", "Chinese"),
                                        'is_loaded_from_db': True,
                                        'filename': doc_title,
                                        'chat_history': doc.get("chat_history", "")
                                    }
                                    chat_history_key = f"chat_history_{doc_id}"
                                    db_history_str = doc.get("chat_history", "")
                                    if db_history_str:
                                        try:
                                            st.session_state[chat_history_key] = json.loads(db_history_str)
                                        except Exception:
                                            st.session_state[chat_history_key] = []
                                    else:
                                        st.session_state[chat_history_key] = []
                                    
                                    st.session_state.is_processing = False
                                    st.toast(f"Loaded summary: {doc_title}!", icon="📥")
                                    st.rerun()
                            with h_col2:
                                if st.button("🗑️", key=f"del_doc_{doc_id}", use_container_width=True, help=f"Delete '{doc_title}'"):
                                    success, msg = delete_summary_from_firestore(uid, doc_id, id_token)
                                    if success:
                                        st.toast(f"Deleted '{doc_title}'!", icon="🗑️")
                                        if 'ocr_results' in st.session_state:
                                            cur_results = st.session_state.ocr_results
                                            if cur_results.get('is_loaded_from_db') and cur_results.get('id') == doc_id:
                                                del st.session_state.ocr_results
                                        st.rerun()
                                    else:
                                        st.error(msg)
                                        
        with p_col2:
            with st.popover("⚙️ Settings", use_container_width=True):
                st.markdown("<h4 style='font-size: 0.95rem; font-weight: 700; color: #1f2937; margin-bottom: 12px;'>Settings & Core</h4>", unsafe_allow_html=True)
                st.markdown("""
                    <div style="background: #F8FAFC; border: 1px solid #E5E7EB; border-radius: 10px; padding: 10px 12px; display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background-color: #10b981; box-shadow: 0 0 8px rgba(16, 185, 129, 0.4);"></span>
                            <span style="font-size: 0.8rem; font-weight: 700; color: #1f2937;">API Status: Online</span>
                        </div>
                        <div style="display: flex; align-items: center; justify-content: space-between; font-size: 0.75rem; color: #4b5563;">
                            <span>⚡ GPU Mode</span>
                            <span style="background: rgba(16, 185, 129, 0.1); color: #059669; font-weight: 700; padding: 1px 6px; border-radius: 4px;">FAST</span>
                        </div>
                        <div style="display: flex; align-items: center; justify-content: space-between; font-size: 0.75rem; color: #4b5563;">
                            <span>🧠 Engine Model</span>
                            <span style="font-family: monospace; font-size: 0.7rem; color: #6366f1; font-weight: 600;">Gemini 1.5 Pro</span>
                        </div>
                    </div>
                """, unsafe_allow_html=True)
                
                if uid:
                    saved_docs, _ = fetch_saved_summaries(uid, id_token)
                    doc_count = len(saved_docs) if saved_docs else 0
                    quota_max = 20
                    percentage = min(int((doc_count / quota_max) * 100), 100)
                    progress_color = "#6366f1" if percentage < 80 else "#ef4444"
                    
                    st.markdown(f"""
                        <div style="padding: 4px 8px;">
                            <div style="display: flex; justify-content: space-between; font-size: 0.75rem; font-weight: 600; color: #4b5563; margin-bottom: 6px;">
                                <span>☁️ Storage Quota</span>
                                <span>{doc_count}/{quota_max} docs</span>
                            </div>
                            <div style="width: 100%; height: 6px; background-color: #e2e8f0; border-radius: 99px; overflow: hidden; display: flex;">
                                <div style="width: {percentage}%; height: 100%; background-color: {progress_color}; border-radius: 99px; transition: width 0.3s ease;"></div>
                            </div>
                            <div style="font-size: 0.68rem; color: #94a3b8; margin-top: 6px;">Upgrade for unlimited docs.</div>
                        </div>
                    """, unsafe_allow_html=True)
                    
        with p_col3:
            user_profile = st.session_state.get('user_profile', {})
            profile_name = user_profile.get('name') or user_name
            profile_role = user_profile.get('role') or 'Standard Account'
            profile_avatar = user_profile.get('avatar', '')
            initials = profile_name[0].upper() if profile_name else "U"
            
            avatar_html = ""
            if profile_avatar:
                avatar_html = f'<img src="{profile_avatar}" style="width: 32px; height: 32px; border-radius: 50%; object-fit: cover; border: none; display: block !important;">'
            else:
                avatar_html = f'<div style="width: 32px; height: 32px; border-radius: 50%; background: #EEF2FF; color: #6366F1; display: flex !important; align-items: center !important; justify-content: center !important; font-weight: 700 !important; font-size: 0.85rem !important; font-family: \'Poppins\', sans-serif !important;">{initials}</div>'
                
            with st.popover("👤 Profile", use_container_width=True):
                st.markdown(f"""
                    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid #E5E7EB;">
                        {avatar_html}
                        <div style="display: flex; flex-direction: column; overflow: hidden;">
                            <span style="font-weight: 700; color: #1f2937; font-size: 0.88rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{profile_name}</span>
                            <span style="font-size: 0.75rem; color: #6b7280; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{profile_role}</span>
                        </div>
                    </div>
                """, unsafe_allow_html=True)
                
                if st.button("⚙️ Edit Profile", key="nav_edit_profile_btn", use_container_width=True):
                    st.session_state.edit_profile_active = True
                    st.session_state.quiz_mode_active = False
                    st.session_state.leaderboard_active = False
                    st.rerun()
                    
                st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
                
                if st.button("🏆 Global Leaderboard", key="nav_leaderboard_btn", use_container_width=True):
                    st.session_state.leaderboard_active = True
                    st.session_state.edit_profile_active = False
                    st.session_state.quiz_mode_active = False
                    st.rerun()
                    
                st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
                
                if st.button("Logout", key="nav_logout_button", use_container_width=True, type="primary"):
                    st.session_state.user = None
                    st.session_state.logout_request = True
                    st.session_state.user_profile = None
                    if 'ocr_results' in st.session_state:
                        del st.session_state.ocr_results
                    if 'quiz_data' in st.session_state:
                        del st.session_state.quiz_data
                    st.session_state.quiz_mode_active = False
                    st.session_state.edit_profile_active = False
                    st.session_state.leaderboard_active = False
                    st.session_state.quiz_finished = False
                    st.session_state.quiz_submitted = False
                    st.session_state.guest_quiz_attempts = []
                    st.rerun()

    
    
    logo_path = "logo.png"
    logo_html_small = ""
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode()
        logo_html_small = f'<img class="hero-logo" src="data:image/png;base64,{encoded_string}">'

    # Initialize variables
    has_results = 'ocr_results' in st.session_state and not st.session_state.is_processing
    uploaded_file = None

    # Render the welcome hero banner and feature cards directly
    st.markdown(f"""
        <div class="hero-container">
            <div style="display: flex; align-items: center; justify-content: center; gap: 20px; margin-bottom: 0.5rem; margin-top: 0.5rem; flex-wrap: wrap;">
                {logo_html_small}
                <h1 class="hero-title" style="margin: 0 !important; line-height: 1 !important;">DocuMind</h1>
            </div>
            <div style="margin-bottom: 1.8rem; display: flex; justify-content: center;">
                <div class="hero-badge">
                    <span>✨</span> AI-Powered Document Intelligence
                </div>
            </div>
            <p class="hero-subtitle">Unlock instant insights, interactive mindmaps, and smart quizzes from any document or image. Powered by state-of-the-art OCR & Gemini LLM.</p>
            <div class="hero-pills">
                <div class="hero-pill"><span>👁️</span> OCR Extraction</div>
                <div class="hero-pill"><span>🧠</span> AI Summary</div>
                <div class="hero-pill"><span>🗺️</span> Interactive Markmap</div>
                <div class="hero-pill"><span>📝</span> Smart Quiz</div>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    st.markdown("""
        <div class="feature-grid">
            <div class="feature-card feature-card-ocr">
                <div class="feature-card-icon">👁️</div>
                <div class="feature-card-title">Advanced OCR</div>
                <div class="feature-card-desc">Accurately parse text from scanned images, PDFs, Word documents, and PowerPoint slides.</div>
            </div>
            <div class="feature-card feature-card-synthesis">
                <div class="feature-card-icon">🧠</div>
                <div class="feature-card-title">AI Synthesis</div>
                <div class="feature-card-desc">Synthesize core findings, translate across multiple languages, and generate document-based quiz games.</div>
            </div>
            <div class="feature-card feature-card-mindmap">
                <div class="feature-card-icon">🗺️</div>
                <div class="feature-card-title">Interactive Mindmap</div>
                <div class="feature-card-desc">Organize concepts visually into interactive markmaps with PDF exports and direct markdown copies.</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # Use session state to handle button disabling
    if 'is_processing' not in st.session_state:
        st.session_state.is_processing = False

    # Render Setup & Upload container
    if has_results:
        setup_container = st.expander("📤 Analyze New Document", expanded=False, key="setup_expander")
    else:
        setup_container = st.container(border=True, key="setup_container")
        
    with setup_container:
        if not has_results:
            st.markdown("<h4 style='margin-top: 0; color: #1e293b; font-family: \"Poppins\", sans-serif;'>📤 Upload & Configure</h4>", unsafe_allow_html=True)
            
        uploaded_file = st.file_uploader(
            "Upload Document or Image", 
            type=["png", "pdf", "docx", "doc", "pptx", "ppt"],
            label_visibility="collapsed" if has_results else "visible"
        )
        
        # 1. Preview / Status Section (Full Width, Centered)
        if uploaded_file is not None:
            file_type = uploaded_file.name.split('.')[-1].lower()
            file_size_kb = round(uploaded_file.size / 1024, 1)
            
            if file_type in ['png']:
                col_img_left, col_img_mid, col_img_right = st.columns([1, 2, 1])
                with col_img_mid:
                    st.image(uploaded_file, caption=f"{uploaded_file.name} • {file_size_kb} KB", use_container_width=True)
            else:
                st.markdown(f"""
                    <div style="background: linear-gradient(135deg, rgba(16, 185, 129, 0.04) 0%, rgba(5, 150, 105, 0.04) 100%); border-radius: 12px; padding: 14px 20px; border: 1px solid rgba(16, 185, 129, 0.2); display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-top: 10px; margin-bottom: 15px; box-shadow: 0 4px 12px rgba(16, 185, 129, 0.03);">
                        <div style="display: flex; align-items: center; gap: 14px;">
                            <span style="font-size: 2rem; line-height: 1;">📄</span>
                            <div>
                                <div style="font-weight: 700; color: #0f172a; font-size: 0.95rem;">{uploaded_file.name}</div>
                                <div style="font-size: 0.8rem; color: #475569; margin-top: 2px; font-weight: 500;">{file_type.upper()} Document • {file_size_kb} KB</div>
                            </div>
                        </div>
                        <span style="background: rgba(16, 185, 129, 0.1); color: #10b981; padding: 4px 10px; border-radius: 99px; font-size: 0.75rem; font-weight: 700; border: 1px solid rgba(16, 185, 129, 0.2);">Ready to Analyze</span>
                    </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown("""
                <div style="background: rgba(255, 255, 255, 0.85); border-left: 3px solid #6366f1; border-radius: 6px; padding: 10px 16px; margin: 15px 0; text-align: left; display: flex; align-items: center; gap: 10px; box-shadow: 0 2px 8px rgba(99, 102, 241, 0.03);">
                    <span style="font-size: 1.15rem;">💡</span>
                    <span style="color: #475569; font-size: 0.9rem; font-weight: 500;">Ready to start? Drag & drop or browse to upload your document (PDF, Docx, PPTx, or Image).</span>
                </div>
            """, unsafe_allow_html=True)
        
        st.markdown("<div style='height: 1px; background: linear-gradient(90deg, rgba(226,232,240,0.1) 0%, rgba(226,232,240,0.8) 50%, rgba(226,232,240,0.1) 100%); margin: 18px 0;'></div>", unsafe_allow_html=True)
        
        # 2. Controls & Actions Row (2 balanced columns: Left = Language Select, Right = Buttons)
        ctrl_col1, ctrl_col2 = st.columns([1, 1], gap="large")
        
        with ctrl_col1:
            target_summary_lang = st.selectbox(
                "🌐 Summary Translation Language", 
                ["Chinese", "Malay", "Japanese", "French", "Spanish", "Korean", "German", "Tamil", "Hindi"],
                key="main_summary_target_lang",
                disabled=st.session_state.get('is_processing', False)
            )
            
        with ctrl_col2:
            st.markdown("<label style='font-size: 0.98rem; font-weight: 700; color: #1e293b; display: inline-block; margin-bottom: 8px;'>⚡ Actions</label>", unsafe_allow_html=True)
            
            # Action Buttons Row
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                button_label = "⌛ Processing..." if st.session_state.is_processing else "▶ Start Analysis"
                is_disabled = st.session_state.is_processing or (uploaded_file is None)
                if st.button(button_label, type="primary", use_container_width=True, disabled=is_disabled, key="main_start_analysis_btn"):
                    st.session_state.is_processing = True
                    if 'quiz_data' in st.session_state: del st.session_state['quiz_data']
                    if 'quiz_submitted' in st.session_state: del st.session_state['quiz_submitted']
                    if 'quiz_mode_active' in st.session_state: st.session_state['quiz_mode_active'] = False
                    st.rerun()
            with btn_col2:
                if has_results:
                    if st.button("🗑️ Clear Results", type="secondary", use_container_width=True, key="main_clear_results_btn"):
                        del st.session_state.ocr_results
                        if 'quiz_data' in st.session_state: del st.session_state['quiz_data']
                        if 'quiz_submitted' in st.session_state: del st.session_state['quiz_submitted']
                        if 'quiz_mode_active' in st.session_state: st.session_state['quiz_mode_active'] = False
                        st.rerun()
                else:
                    st.button("🗑️ Clear Results", type="secondary", use_container_width=True, disabled=True, key="main_clear_disabled_btn")

    if st.session_state.is_processing:
        if not api_key:
            st.error("Please enter your Gemini API Key in the sidebar first!")
            st.session_state.is_processing = False
            return

        try:
            # Progress placeholder
            my_bar = st.progress(0, text="Initializing analysis...")
            status_placeholder = st.empty()

            # Dynamic results area with loading animation
            results_placeholder = st.empty()
            with results_placeholder.container():
                st.markdown("<div style='margin-top: 2rem; text-align: center;'>", unsafe_allow_html=True)
                st.spinner("Synthesizing your document details...")
                st.markdown("</div>", unsafe_allow_html=True)

            # Step 1: OCR
            status_placeholder.markdown("🔍 <span style='color: #f59e0b; font-weight: 600;'>Step 1/2:</span> Extracting text...", unsafe_allow_html=True)
            my_bar.progress(10, text="🔍 OCR Engine: Extracting text components...")
            
            from ocr_engine import extract_text_from_image
            start_time = time.time()
            uploaded_file.seek(0)
            
            def update_progress(current, total):
                percent = min(10 + int((current / total) * 40), 50)
                my_bar.progress(percent, text=f"🔍 OCR Engine: Processing page {current}/{total}...")
                status_placeholder.markdown(f"🔍 <span style='color: #f59e0b; font-weight: 600;'>Step 1/2:</span> Extracting text ({current}/{total})...", unsafe_allow_html=True)

            raw_text = extract_text_from_image(uploaded_file, progress_callback=update_progress)
            ocr_time = time.time() - start_time
            
            if not raw_text or "⚠️" in raw_text:
                st.warning(raw_text if raw_text else "No text detected.")
                st.session_state.is_processing = False
                return

            # Step 2: LLM Summarization
            status_placeholder.markdown("🧠 <span style='color: #f59e0b; font-weight: 600;'>Step 2/4:</span> Generating AI summary...", unsafe_allow_html=True)
            my_bar.progress(50, text="🧠 AI Brain: Synthesizing intelligent summary...")
            
            from summarizer import summarize_text
            summary_result = summarize_text(raw_text, api_key)
            
            # Step 3: Translation
            status_placeholder.markdown(f"🏮 <span style='color: #f59e0b; font-weight: 600;'>Step 3/4:</span> Translating to {st.session_state.main_summary_target_lang}...", unsafe_allow_html=True)
            my_bar.progress(70, text="🧠 AI Brain: Translating findings...")
            from summarizer import translate_text
            translation_result = translate_text(summary_result, api_key, target_language=st.session_state.main_summary_target_lang)

            # Step 4: Mindmap Generation
            status_placeholder.markdown("🗺️ <span style='color: #f59e0b; font-weight: 600;'>Step 4/4:</span> Generating interactive mindmap...", unsafe_allow_html=True)
            my_bar.progress(85, text="🧠 AI Brain: Designing interactive mindmap...")
            from summarizer import generate_mindmap
            mindmap_eng = generate_mindmap(summary_result, api_key, target_language="English")
            mindmap_trans = translate_text(mindmap_eng, api_key, target_language=st.session_state.main_summary_target_lang)

            # Complete
            my_bar.progress(100, text="✅ Analysis successfully completed!")
            status_placeholder.markdown("✨ <span style='color: #10b981; font-weight: 700;'>Complete!</span> Findings are ready below.", unsafe_allow_html=True)
            time.sleep(1)
            my_bar.empty()
            st.toast("Analysis complete!", icon="✅")
            
            # Clean filename by stripping the file extension
            clean_filename = uploaded_file.name if uploaded_file else ""
            if clean_filename and '.' in clean_filename:
                clean_filename = '.'.join(clean_filename.split('.')[:-1])
                
            # Store results in session state so they persist after rerun
            st.session_state.ocr_results = {
                'filename': clean_filename,
                'raw_text': raw_text,
                'summary': summary_result,
                'translation': translation_result,
                'mindmap_eng': mindmap_eng,
                'mindmap_trans': mindmap_trans,
                'time': ocr_time,
                'lang': st.session_state.main_summary_target_lang
            }
            st.session_state.is_processing = False
            st.rerun()

        except Exception as e:
            st.error(f"An unexpected error occurred: {str(e)}")
            st.session_state.is_processing = False
            return

    # Display results if they exist in session state
    if 'ocr_results' in st.session_state and not st.session_state.is_processing:
        results = st.session_state.ocr_results
        raw_text = results['raw_text']
        summary_result = results['summary']
        translation_result = results.get('translation', '')
        ocr_time = results['time']
        result_lang = results.get('lang', 'Chinese')
        
        # Calculate stats
        page_count = max(1, raw_text.count('-- Page '))
        word_count = len(raw_text.split())
        is_saved = results.get('is_loaded_from_db', False)

        # ── Row 1: Title (full width) ──────────────────────────────────
        st.markdown("<h2 style='font-size: 2.0rem; font-weight: 800; color: #0f172a; margin: 0 0 6px 0; font-family: \"Poppins\", sans-serif; display: flex; align-items: center; gap: 10px;'>✨ Analysis Results</h2>", unsafe_allow_html=True)

        # Prepare data for Export popover (needed regardless of rename mode)
        from doc_generator import generate_docx
        docx_data = generate_docx(summary_result, translation_result, result_lang)
        md_text = f"# {results.get('filename', 'DocuMind Summary')}\n\n{summary_result}"
        if translation_result:
            md_text += f"\n\n---\n\n## Translation ({result_lang})\n\n{translation_result}"
        md_data = md_text.encode('utf-8')

        filename = results.get('filename', 'Direct Upload')
        doc_id = results.get('id', '')
        rename_key = f"renaming_doc_{doc_id}"

        if is_saved and st.session_state.get(rename_key, False):
            # ── INLINE RENAME MODE ──────────────────────────────────────
            rename_col, export_col_r, spacer_r = st.columns([3, 1.2, 1.5])
            with rename_col:
                with st.form(key=f"rename_form_{doc_id}", clear_on_submit=False):
                    typed_name = st.text_input(
                        "New document name",
                        value=filename,
                        label_visibility="collapsed",
                        placeholder="Enter new document name..."
                    )
                    f_col1, f_col2 = st.columns([1, 1])
                    with f_col1:
                        submitted = st.form_submit_button("✅ Save", use_container_width=True, type="primary")
                    with f_col2:
                        cancelled = st.form_submit_button("✖ Cancel", use_container_width=True)

                if submitted:
                    new_name = typed_name.strip()
                    if new_name:
                        user_info = st.session_state.get("user")
                        uid_r = user_info.get("uid") if user_info else None
                        id_token_r = user_info.get("idToken") if user_info else None
                        if uid_r and doc_id:
                            ok, err = rename_document_title(uid_r, doc_id, new_name, id_token_r)
                            if ok:
                                st.session_state.ocr_results['filename'] = new_name
                                st.session_state[rename_key] = False
                                st.toast(f"✅ Renamed to \"{new_name}\"", icon="✏️")
                                st.rerun()
                            else:
                                st.error(f"❌ Rename failed — {err}")
                        else:
                            st.warning(f"Cannot rename: doc_id='{doc_id}' | uid='{uid_r}'")
                    else:
                        st.warning("Name cannot be empty.")

                if cancelled:
                    st.session_state[rename_key] = False
                    st.rerun()
            with export_col_r:
                st.markdown("<div style='margin-top: 4px;'></div>", unsafe_allow_html=True)
                with st.popover("📤 Export Document", use_container_width=True, key="export_document_popover"):
                    st.download_button(label="📄 Export as Word (.docx)", data=docx_data, file_name=f"{results.get('filename', 'DocuMind')}_Summary.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True, key="export_word_btn")
                    st.download_button(label="📝 Export as Markdown (.md)", data=md_data, file_name=f"{results.get('filename', 'DocuMind')}_Summary.md", mime="text/markdown", use_container_width=True, key="export_md_btn")
                    copy_to_clipboard(summary_result, "Copy Summary Markdown")
        else:
            # ── Row 2: [badge] [✏️] [Export Document] [spacer] ──────────
            badge_col, pencil_col, export_col, spacer_col = st.columns(
                [2.2, 0.22, 1.2, 2.1], gap="small", vertical_alignment="center"
            )
            with badge_col:
                st.markdown(
                    f"<div style='background-color: rgba(99, 102, 241, 0.08); color: #6366f1; font-size: 0.85rem; font-weight: 600; padding: 6px 14px; border-radius: 8px; display: inline-flex; align-items: center; gap: 6px; border: 1px solid rgba(99, 102, 241, 0.15);'>"
                    f"📂 Active Document: <strong>{filename}</strong>"
                    f"</div>",
                    unsafe_allow_html=True
                )
            with pencil_col:
                if is_saved:
                    if st.button("✏️", key=f"rename_btn_{doc_id}", help="Rename this document"):
                        st.session_state[rename_key] = True
                        st.rerun()
            with export_col:
                with st.popover("📤 Export Document", use_container_width=True, key="export_document_popover"):
                    st.download_button(label="📄 Export as Word (.docx)", data=docx_data, file_name=f"{results.get('filename', 'DocuMind')}_Summary.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True, key="export_word_btn")
                    st.download_button(label="📝 Export as Markdown (.md)", data=md_data, file_name=f"{results.get('filename', 'DocuMind')}_Summary.md", mime="text/markdown", use_container_width=True, key="export_md_btn")
                    copy_to_clipboard(summary_result, "Copy Summary Markdown")

        # ── Row 3: Stats bar ─────────────────────────────────────────────
        db_badge_html = (
            '  •  <span style="background-color: rgba(16, 185, 129, 0.1); color: #059669; font-size: 0.78rem; font-weight: 700; padding: 3px 10px; border-radius: 99px; display: inline-flex; align-items: center; vertical-align: middle; gap: 4px;">'
            '☁️ Cloud Saved'
            '</span>'
        ) if is_saved else ""
        st.markdown(
            f"<div style='font-size: 0.98rem; color: #475569; font-weight: 500; margin-top: 8px; margin-bottom: 24px; display: flex; align-items: center; flex-wrap: wrap; gap: 6px;'>"
            f"⏱️ {ocr_time:.2f}s  •  📊 {word_count} words  •  📄 {page_count} pages{db_badge_html}"
            f"</div>",
            unsafe_allow_html=True
        )


        # Cloud Database Saving UI (Flat layout Notion-style)
        if not is_saved:
            with st.container():
                st.markdown("<h5 style='font-size: 0.95rem; font-weight: 700; color: #374151; margin-bottom: 8px;'>☁️ Save Summary to Cloud Database</h5>", unsafe_allow_html=True)
                s_col1, s_col2 = st.columns([3.5, 1])
                with s_col1:
                    doc_filename = results.get('filename', '')
                    if doc_filename and '.' in doc_filename:
                        doc_filename = '.'.join(doc_filename.split('.')[:-1])
                    default_title = doc_filename if doc_filename else f"Summary_{datetime.now().strftime('%m%d_%H%M')}"
                    doc_title = st.text_input("Document Title", value=default_title, key="save_doc_title_input", label_visibility="collapsed")
                with s_col2:
                    save_clicked = st.button("💾 Save to Account", use_container_width=True, type="primary")
                
                if save_clicked:
                    user_info = st.session_state.get("user")
                    if user_info:
                        uid = user_info.get("uid")
                        id_token = user_info.get("idToken")
                        
                        # Get current chat history for new upload (currently under default_doc)
                        old_chat_key = "chat_history_default_doc"
                        current_chat_history = st.session_state.get(old_chat_key, [])
                        
                        with st.spinner("Saving to database..."):
                            success, msg = save_summary_to_firestore(
                                uid=uid,
                                id_token=id_token,
                                title=doc_title,
                                raw_text=raw_text,
                                summary_text=summary_result,
                                translation_text=translation_result,
                                lang=result_lang,
                                mindmap_eng=results.get('mindmap_eng', ''),
                                mindmap_trans=results.get('mindmap_trans', ''),
                                chat_history=current_chat_history
                            )
                            if success:
                                new_doc_id = msg
                                if 'ocr_results' in st.session_state:
                                    st.session_state.ocr_results['id'] = new_doc_id
                                    st.session_state.ocr_results['is_loaded_from_db'] = True
                                    st.session_state.ocr_results['filename'] = doc_title
                                    # Copy the default chat history key to the new document ID key
                                    new_chat_key = f"chat_history_{new_doc_id}"
                                    st.session_state[new_chat_key] = current_chat_history
                                    # Clear default doc key
                                    st.session_state[old_chat_key] = []
                                st.toast("Successfully saved to your account database!", icon="✅")
                                st.rerun()
                            else:
                                st.error(msg)
                    else:
                        st.error("User not authenticated.")

        st.markdown("<br>", unsafe_allow_html=True)

        main_col, chat_col = st.columns([1.6, 1.0], gap="large")

        with chat_col:
            with st.container(border=True, key="chatbot_container"):
                render_left_panel(raw_text, summary_result, api_key, results)

        with main_col:
            tab1, tab2, tab3, tab4 = st.tabs(["Summary", f"🌐 {result_lang} Translation", "🗺️ Mind Map", "📝 Quiz"])
            
            with tab1:
                sum_col1, sum_col2 = st.columns([6, 4], vertical_alignment="center")
                with sum_col1:
                    st.markdown("#### ✨ AI Summary")
                with sum_col2:
                    copy_to_clipboard(summary_result, "Copy Summary")
                
                st.markdown(summary_result)
                st.markdown("---")
                with st.expander("👁️ View Raw Extracted Text", expanded=False):
                    st.text_area("Extracted OCR Text", raw_text, height=350, disabled=True, label_visibility="collapsed")
                
            with tab2:
                # Dynamic translation update
                t_col1, t_col2 = st.columns([3, 1])
                with t_col1:
                    available_langs = ["Chinese", "Malay", "Japanese", "French", "Spanish", "Korean", "German", "Tamil", "Hindi"]
                    current_idx = available_langs.index(result_lang) if result_lang in available_langs else 0
                    new_lang = st.selectbox(
                        "Change Language:", 
                        available_langs,
                        index=current_idx,
                        key="dynamic_lang_select_tab2",
                        label_visibility="collapsed"
                    )
                with t_col2:
                    translate_clicked = st.button("🔄 Translate", use_container_width=True)
                
                if translate_clicked and new_lang != result_lang:
                    with st.spinner(f"Translating to {new_lang}..."):
                        from summarizer import translate_text, generate_mindmap
                        new_translation = translate_text(summary_result, api_key, target_language=new_lang)
                        
                        # Retrieve or generate the English mindmap first
                        mindmap_eng = results.get('mindmap_eng', '')
                        if not mindmap_eng:
                            mindmap_eng = generate_mindmap(summary_result, api_key, target_language="English")
                            st.session_state.ocr_results['mindmap_eng'] = mindmap_eng
                        
                        # Translate the English mindmap to the new language
                        new_mindmap_trans = translate_text(mindmap_eng, api_key, target_language=new_lang)
                        
                        st.session_state.ocr_results['translation'] = new_translation
                        st.session_state.ocr_results['mindmap_trans'] = new_mindmap_trans
                        st.session_state.ocr_results['lang'] = new_lang
                        st.rerun()
                
                st.markdown("<hr style='margin: 0.5rem 0; opacity: 0.2;'>", unsafe_allow_html=True)
                
                if translation_result:
                    copy_to_clipboard(translation_result, f"Copy {result_lang} Translation")
                    st.markdown(translation_result)
                else:
                    st.info("No translation available.")
                    
            with tab3:
                st.markdown("### 🗺️ Interactive Mindmap")
                st.caption("Visually navigate the core concepts and structure of your document.")
                
                # Fetch mindmaps from results
                mindmap_eng = results.get('mindmap_eng', '')
                mindmap_trans = results.get('mindmap_trans', '')
                
                # Language toggle for mindmap
                m_lang = st.radio(
                    "Mindmap Language:",
                    ["English", result_lang],
                    index=1 if result_lang else 0,
                    horizontal=True,
                    key="mindmap_lang_selection"
                )
                
                selected_mindmap = mindmap_trans if m_lang == result_lang else mindmap_eng
                
                if not selected_mindmap:
                    st.info("No mindmap data found. Generating now...")
                    with st.spinner("Generating mindmap..."):
                        from summarizer import generate_mindmap
                        mindmap_eng = generate_mindmap(summary_result, api_key, target_language="English")
                        mindmap_trans = translate_text(mindmap_eng, api_key, target_language=result_lang)
                        st.session_state.ocr_results['mindmap_eng'] = mindmap_eng
                        st.session_state.ocr_results['mindmap_trans'] = mindmap_trans
                        st.rerun()
                
                # Escape the markdown content safely to insert into JavaScript/HTML template
                escaped_mindmap = selected_mindmap.replace("</script>", "<\\/script>")
                
                markmap_html = f"""
                <!DOCTYPE html>
                <html>
                <head>
                  <meta charset="UTF-8">
                  <style>
                    html, body {{
                      margin: 0;
                      padding: 0;
                      width: 100%;
                      height: 100%;
                      overflow: hidden;
                      background-color: #f8fafc;
                      background-image: 
                        radial-gradient(at 0% 0%, rgba(199, 210, 254, 0.15) 0px, transparent 50%),
                        radial-gradient(at 100% 0%, rgba(251, 207, 232, 0.15) 0px, transparent 50%),
                        radial-gradient(at 50% 100%, rgba(165, 180, 252, 0.1) 0px, transparent 50%);
                      font-family: 'Inter', system-ui, -apple-system, sans-serif;
                    }}
                    .markmap {{
                      width: 100%;
                      height: 100%;
                    }}
                    .markmap svg {{
                      width: 100%;
                      height: 100%;
                      background-color: transparent;
                    }}
                    /* Node custom styles */
                    .markmap-node text {{
                      font-family: 'Inter', system-ui, -apple-system, sans-serif !important;
                      font-weight: 500 !important;
                      transition: fill 0.2s ease;
                    }}
                    .markmap-node:hover text {{
                      fill: #4f46e5 !important;
                    }}
                    .markmap-node-depth-0 text {{
                      font-size: 16px !important;
                      font-weight: 700 !important;
                      fill: #1e1b4b !important;
                    }}
                    .markmap-node-depth-1 text {{
                      font-size: 13px !important;
                      font-weight: 600 !important;
                      fill: #312e81 !important;
                    }}
                    .markmap-node-depth-2 text {{
                      font-size: 11px !important;
                      fill: #0f172a !important;
                    }}
                    /* Link styles */
                    path.markmap-link {{
                      stroke-width: 2px !important;
                      transition: stroke-width 0.2s, stroke 0.2s;
                    }}
                    .markmap-node:hover ~ path.markmap-link {{
                      stroke: #6366f1 !important;
                      stroke-width: 3px !important;
                    }}
                    /* Custom toolbar style */
                    .markmap-toolbar {{
                      position: absolute !important;
                      bottom: 20px !important;
                      right: 20px !important;
                      background: rgba(255, 255, 255, 0.7) !important;
                      backdrop-filter: blur(12px) !important;
                      -webkit-backdrop-filter: blur(12px) !important;
                      border: 1px solid rgba(255, 255, 255, 0.5) !important;
                      border-radius: 30px !important;
                      box-shadow: 0 10px 30px -10px rgba(0, 0, 0, 0.1) !important;
                      padding: 6px 12px !important;
                      display: flex !important;
                      gap: 8px !important;
                      align-items: center !important;
                    }}
                    .markmap-toolbar-item {{
                      width: 28px !important;
                      height: 28px !important;
                      border-radius: 50% !important;
                      display: inline-flex !important;
                      align-items: center !important;
                      justify-content: center !important;
                      color: #4f46e5 !important;
                      background: transparent !important;
                      border: none !important;
                      transition: all 0.2s !important;
                      cursor: pointer !important;
                    }}
                    .markmap-toolbar-item:hover {{
                      background: rgba(79, 70, 229, 0.1) !important;
                      transform: scale(1.1) !important;
                    }}
                    /* Premium Download Button */
                    .download-btn {{
                      position: absolute !important;
                      top: 16px !important;
                      right: 16px !important;
                      background: rgba(255, 255, 255, 0.85) !important;
                      backdrop-filter: blur(8px) !important;
                      -webkit-backdrop-filter: blur(8px) !important;
                      border: 1px solid rgba(226, 232, 240, 0.8) !important;
                      border-radius: 8px !important;
                      color: #4f46e5 !important;
                      font-size: 0.8rem !important;
                      font-weight: 600 !important;
                      padding: 6px 12px !important;
                      cursor: pointer !important;
                      transition: all 0.2s !important;
                      display: inline-flex !important;
                      align-items: center !important;
                      gap: 6px !important;
                      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05) !important;
                      z-index: 1000 !important;
                    }}
                    .download-btn:hover {{
                      background: #4f46e5 !important;
                      color: #ffffff !important;
                      border-color: #4f46e5 !important;
                      transform: translateY(-1px) !important;
                      box-shadow: 0 6px 16px rgba(79, 70, 229, 0.2) !important;
                    }}
                  </style>
                  <script>
                    window.markmap = {{
                      autoLoader: {{
                        toolbar: true,
                      }},
                    }};
                  </script>
                  <script src="https://cdn.jsdelivr.net/npm/markmap-autoloader"></script>
                  <!-- html2canvas and jsPDF for exporting to PDF -->
                  <script src="https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js"></script>
                  <script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"></script>
                  <script>
                    function downloadPDF() {{
                      const toolbar = document.querySelector('.markmap-toolbar');
                      const btn = document.querySelector('.download-btn');
                      
                      // Hide UI elements during print capture
                      if (toolbar) toolbar.style.display = 'none';
                      if (btn) btn.style.display = 'none';
                      
                      const element = document.body;
                      const width = element.clientWidth;
                      const height = element.clientHeight;
                      
                      html2canvas(element, {{
                        scale: 2,
                        useCORS: true,
                        logging: false,
                        backgroundColor: '#f8fafc'
                      }}).then(canvas => {{
                        const imgData = canvas.toDataURL('image/jpeg', 0.98);
                        
                        const {{ jsPDF }} = window.jspdf;
                        const pdf = new jsPDF({{
                          orientation: 'landscape',
                          unit: 'pt',
                          format: [width, height]
                        }});
                        
                        pdf.addImage(imgData, 'JPEG', 0, 0, width, height);
                        pdf.save('DocuMind_Mindmap.pdf');
                        
                        // Restore UI elements
                        if (toolbar) toolbar.style.display = 'flex';
                        if (btn) btn.style.display = 'flex';
                      }}).catch(err => {{
                        console.error(err);
                        if (toolbar) toolbar.style.display = 'flex';
                        if (btn) btn.style.display = 'flex';
                      }});
                    }}
                  </script>
                </head>
                <body>
                  <button class="download-btn" onclick="downloadPDF()">
                    <span>📥</span> Download PDF
                  </button>
                  <div class="markmap">
                    <script type="text/template">
                      {escaped_mindmap}
                    </script>
                  </div>
                </body>
                </html>
                """
                
                # Render inside an iframe component
                components.html(markmap_html, height=500)
                
                with st.expander("📋 View/Copy Mindmap Markdown Source", expanded=False):
                    st.code(selected_mindmap, language="markdown")
                    
            with tab4:
                st.markdown("### 📝 Document-Based Smart Quiz")
                st.caption("Test your understanding of the document's core content")
                
                # Check user info
                user_info = st.session_state.get("user")
                uid = user_info.get("uid") if user_info else None
                id_token = user_info.get("idToken") if user_info else None
                
                # Helper to normalize topic names for robust matching (ignoring casing, extensions, spaces/separators)
                def normalize_topic_for_match(name):
                    if not name:
                        return ""
                    import re
                    s = name.lower()
                    if '.' in s:
                        s = '.'.join(s.split('.')[:-1])
                    return re.sub(r'[^a-z0-9]', '', s)
                
                # Load progression and history
                if uid:
                    progression, prog_err = fetch_user_progression(uid, id_token)
                    if prog_err or not progression:
                        progression = {"xp": 0, "level": 1, "badges": []}
                    
                    all_history, hist_err = fetch_quiz_attempts(uid, id_token)
                    if hist_err or not all_history:
                        all_history = []
                        
                    # Self-healing: if progression XP is 0 but quiz history exists, restore XP
                    if progression.get("xp", 0) == 0 and all_history:
                        total_xp_calc = sum(int(att.get("xp_earned", 0)) for att in all_history)
                        if total_xp_calc > 0:
                            update_user_xp_level(uid, id_token, total_xp_calc)
                            progression, _ = fetch_user_progression(uid, id_token)
                            if not progression:
                                progression = {"xp": 0, "level": 1, "badges": []}
                        
                    # Filter history to only include attempts for the current courseware
                    current_topic = st.session_state.ocr_results.get("filename", "Direct Upload") if 'ocr_results' in st.session_state else "General"
                    norm_current = normalize_topic_for_match(current_topic)
                    history = [att for att in all_history if normalize_topic_for_match(att.get("topic")) == norm_current]
                else:
                    progression = {"xp": 0, "level": 1, "badges": []}
                    # Load guest attempts from local session state
                    all_history = st.session_state.get("guest_quiz_attempts", [])
                    current_topic = st.session_state.ocr_results.get("filename", "Direct Upload") if 'ocr_results' in st.session_state else "General"
                    norm_current = normalize_topic_for_match(current_topic)
                    history = [att for att in all_history if normalize_topic_for_match(att.get("topic")) == norm_current]
                
                # Active Quiz Session Card (if exists in state)
                if st.session_state.get('quiz_data') is not None:
                    with st.container(border=True):
                        st.markdown("""
                            <div style='display: flex; align-items: center; justify-content: space-between;'>
                                <div>
                                    <h5 style='margin: 0; color: #6366f1;'>🎒 Active Quiz Session</h5>
                                    <p style='margin: 0; font-size: 0.8rem; color: #64748b;'>You have a quiz generated and ready to attempt.</p>
                                </div>
                            </div>
                        """, unsafe_allow_html=True)
                        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
                        col_act1, col_act2 = st.columns(2)
                        with col_act1:
                            if st.button("Resume Quiz ➡️", type="primary", use_container_width=True, key="resume_quiz_btn"):
                                st.session_state.quiz_mode_active = True
                                st.rerun()
                        with col_act2:
                            if st.button("Discard Quiz ❌", use_container_width=True, key="discard_quiz_btn"):
                                st.session_state.quiz_data = None
                                st.session_state.is_retry = False
                                st.session_state.parent_attempt_id = ""
                                st.rerun()
                        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
                
                # 1. Combined Progression & Configuration Card
                with st.container(border=True):
                    if uid:
                        current_xp = progression.get("xp", 0)
                        current_level = progression.get("level", 1)
                        badges = progression.get("badges", [])
                        
                        level_xp = current_xp % 500
                        xp_percent = min(int((level_xp / 500) * 100), 100)
                        
                        badge_display_html = ""
                        badge_meta = {
                            "first_steps": ("🏅 First Steps", "Completed 1st quiz"),
                            "perfectionist": ("🏆 Perfectionist", "10/10 on Medium/Hard"),
                            "speed_demon": ("⚡ Speed Demon", "Quiz in <2 mins with >=8/10 score"),
                            "persistence": ("💪 Persistence", "100% on Retry Wrong quiz"),
                            "level_5_master": ("🎓 Level 5 Master", "Reached Level 5"),
                            "level_10_legend": ("👑 Level 10 Legend", "Reached Level 10")
                        }
                        
                        for b_id in badges:
                            if b_id in badge_meta:
                                name, desc = badge_meta[b_id]
                                badge_display_html += f'<span class="badge-tag" title="{desc}">{name}</span>'
                                
                        st.markdown(f"""
                            <style>
                            .badge-tag {{
                                background: rgba(99, 102, 241, 0.1);
                                color: #6366f1;
                                padding: 3px 8px;
                                border-radius: 99px;
                                font-size: 0.85rem;
                                font-weight: 700;
                                border: 1px solid rgba(99, 102, 241, 0.2);
                                display: inline-block;
                                margin-left: 6px;
                                margin-bottom: 2px;
                            }}
                            .progression-row {{
                                display: flex;
                                justify-content: space-between;
                                align-items: center;
                                flex-wrap: wrap;
                                gap: 12px;
                                margin-bottom: 8px;
                            }}
                            div[class*="st-key-generate_quiz_action_btn"] button,
                            div[class*="st-key-generate_quiz_action_btn"] button *,
                            .st-key-generate_quiz_action_btn button,
                            .st-key-generate_quiz_action_btn button * {{
                                color: #FFFFFF !important;
                                font-weight: 700 !important;
                            }}
                            </style>
                            <div class="progression-row">
                                <div style="display: flex; align-items: center; gap: 8px;">
                                    <span style="font-size: 1.4rem; background: linear-gradient(135deg, #8b5cf6 0%, #6366f1 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: 800;">⚡ Level {current_level}</span>
                                    <span style="font-size: 0.95rem; color: #64748b; font-weight: 600;">({current_xp} XP Total)</span>
                                </div>
                                <div style="font-size: 0.95rem; color: #475569; font-weight: 700;">{level_xp} / 500 XP to next level</div>
                            </div>
                            <div style="width: 100%; height: 6px; background-color: #e2e8f0; border-radius: 99px; overflow: hidden; display: flex; margin-bottom: 12px;">
                                <div style="width: {xp_percent}%; height: 100%; background: linear-gradient(90deg, #8b5cf6 0%, #6366f1 100%); border-radius: 99px;"></div>
                            </div>
                            <div style="display: flex; align-items: center; flex-wrap: wrap; margin-bottom: 16px; font-size: 0.9rem;">
                                <span style="font-weight: 700; color: #475569;">🏅 Earned Badges:</span>
                                {badge_display_html if badge_display_html else '<span style="color: #94a3b8; font-style: italic; margin-left: 6px;">No badges unlocked yet.</span>'}
                            </div>
                            <div style="border-top: 1px solid rgba(226, 232, 240, 0.6); margin-bottom: 16px;"></div>
                        """, unsafe_allow_html=True)
                    else:
                        st.info("☁️ Log in to save your history, earn XP, and unlock badges!", icon="☁️")
                        st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

                    st.markdown("<h6 style='margin-top: 0; margin-bottom: 14px; color: #1e293b; font-family: \"Poppins\", sans-serif; font-weight: 700; font-size: 1.15rem;'>⚙️ Configure New Custom Quiz</h6>", unsafe_allow_html=True)
                    
                    config_col1, config_col2, config_col3 = st.columns([1, 1, 1])
                    
                    with config_col1:
                        quiz_difficulty = st.selectbox("🎯 Difficulty Level", ["Easy", "Medium", "Hard"], index=1, help="Adjusts question vocabulary, complexity, and proof-reasoning requirements.")
                    with config_col2:
                        timer_option = st.selectbox("⏱️ Time Limit", ["No Limit", "5 Minutes", "10 Minutes", "15 Minutes"], index=0, help="Optional countdown timer to challenge your speed.")
                    with config_col3:
                        target_lang = st.selectbox("🌐 Translation Language", ["Chinese", "Malay", "Japanese", "French", "Spanish", "Korean", "German", "Tamil", "Hindi"])
                        
                    st.session_state.quiz_target_lang = target_lang
                    st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)
                    
                    if st.button("🚀 Generate Custom Quiz", type="primary", use_container_width=True, key="generate_quiz_action_btn"):
                        with st.spinner(f"AI is generating a [{quiz_difficulty}] quiz with [{timer_option}] time limit, please wait..."):
                            from summarizer import generate_quiz
                            raw_json, err = generate_quiz(summary_result, api_key, target_lang, quiz_difficulty)
                            if err:
                                st.error(err)
                            else:
                                try:
                                    cleaned_json = raw_json.strip()
                                    if cleaned_json.startswith("```json"):
                                        cleaned_json = cleaned_json[7:]
                                    elif cleaned_json.startswith("```"):
                                        cleaned_json = cleaned_json[3:]
                                    if cleaned_json.endswith("```"):
                                        cleaned_json = cleaned_json[:-3]
                                    
                                    import re
                                    sanitized_json = re.sub(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r'\\\\', cleaned_json)
                                    parsed_data = json.loads(sanitized_json, strict=False)
                                    
                                    import random
                                    # Shuffle options to avoid LLM biases
                                    for q in parsed_data:
                                        opts_en = q.get('options', [])
                                        opts_trans = q.get('options_trans', [])
                                        correct_ans_raw = q.get('correct_answer', '')

                                        if isinstance(opts_en, list) and len(opts_en) > 1:
                                            if isinstance(opts_trans, list) and len(opts_en) == len(opts_trans):
                                                combined = list(zip(opts_en, opts_trans))
                                                random.shuffle(combined)
                                                shuffled_en, shuffled_trans = zip(*combined)
                                                opts_en = list(shuffled_en)
                                                opts_trans = list(shuffled_trans)
                                            else:
                                                random.shuffle(opts_en)

                                        # Add A, B, C, D prefixes
                                        prefixed_en = []
                                        prefixed_trans = []
                                        
                                        for i, opt in enumerate(opts_en):
                                            prefix = f"{chr(65+i)}. " # A., B., C., D.
                                            prefixed_en.append(prefix + str(opt))
                                            if str(opt) == str(correct_ans_raw):
                                                q['correct_answer'] = prefix + str(opt)

                                        for i, opt in enumerate(opts_trans):
                                            prefix = f"{chr(65+i)}. "
                                            prefixed_trans.append(prefix + str(opt))

                                        q['options'] = prefixed_en
                                        q['options_trans'] = prefixed_trans
                                                
                                    st.session_state.quiz_data = parsed_data
                                    st.session_state.quiz_mode_active = True
                                    st.session_state.current_q_index = 0
                                    st.session_state.quiz_finished = False
                                    st.session_state.review_mode = False
                                    st.session_state.is_retry = False
                                    st.session_state.parent_attempt_id = ""
                                    st.session_state.quiz_difficulty = quiz_difficulty
                                    
                                    # Timer setup
                                    st.session_state.quiz_time_limit_minutes = 0
                                    if timer_option != "No Limit":
                                        mins = int(timer_option.split(" ")[0])
                                        st.session_state.quiz_time_limit_minutes = mins
                                        st.session_state.quiz_timer_start = time.time()
                                    else:
                                        st.session_state.quiz_timer_start = time.time() # track time anyway
                                    
                                    for key in list(st.session_state.keys()):
                                        if key.startswith('user_ans_') or key.startswith('radio_q_') or key.startswith('q_submitted_'):
                                            del st.session_state[key]
                                            
                                    st.rerun()
                                except Exception as e:
                                    st.error("The content generated by the LLM does not match the standard JSON format, please try again!\n" + str(e))
                                    with st.expander("Show Raw LLM Output"):
                                        st.text(raw_json)

                # 2. Performance Analytics
                if history:
                    st.markdown("<hr style='border: 0; border-top: 1px solid #e2e8f0; margin: 25px 0;'>", unsafe_allow_html=True)
                    st.markdown("#### 📊 Quiz Analytics & Insights")
                    # Calculate total stats
                    total_quizzes = len(history)
                    total_correct = 0
                    total_questions = 0
                    difficulty_counts = {"Easy": 0, "Medium": 0, "Hard": 0}
                    total_xp_earned = 0
                    scores = []
                    
                    for att in history:
                        total_correct += att.get("score", 0)
                        total_questions += att.get("total_questions", 10)
                        diff = att.get("difficulty", "Medium")
                        difficulty_counts[diff] = difficulty_counts.get(diff, 0) + 1
                        total_xp_earned += att.get("xp_earned", 0)
                        scores.append(att.get("score", 0))
                        
                    total_incorrect = max(0, total_questions - total_correct)
                    correct_percent = (total_correct / total_questions * 100) if total_questions else 0
                    incorrect_percent = 100 - correct_percent if total_questions else 0
                    
                    # Find preferred difficulty
                    pref_difficulty = max(difficulty_counts, key=difficulty_counts.get) if total_quizzes > 0 else "Medium"
                    avg_duration = sum(att.get("time_taken_seconds", 0) for att in history) // max(1, total_quizzes)
                    
                    # Average score math
                    avg_score = total_correct / total_quizzes if total_quizzes else 0
                    avg_total = total_questions / total_quizzes if total_quizzes else 10
                    
                    # Custom Visual Stacked Bar
                    st.markdown(f"""<style>
.accuracy-container {{
background: #ffffff;
border: 1px solid #e2e8f0;
border-radius: 12px;
padding: 18px;
box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.02);
margin-bottom: 15px;
}}
.accuracy-bar-wrapper {{
display: flex;
width: 100%;
height: 24px;
border-radius: 99px;
overflow: hidden;
background: #f1f5f9;
margin: 12px 0;
}}
.accuracy-bar-correct {{
width: {correct_percent}%;
background: linear-gradient(90deg, #10b981 0%, #059669 100%);
color: white;
font-size: 0.9rem;
font-weight: 700;
line-height: 24px;
text-align: center;
transition: width 0.3s ease;
}}
.accuracy-bar-incorrect {{
width: {incorrect_percent}%;
background: linear-gradient(90deg, #ef4444 0%, #dc2626 100%);
color: white;
font-size: 0.9rem;
font-weight: 700;
line-height: 24px;
text-align: center;
transition: width 0.3s ease;
}}
.stat-grid-mini {{
display: grid;
grid-template-columns: repeat(3, 1fr);
gap: 10px;
margin-top: 15px;
}}
.stat-item-mini {{
text-align: center;
padding: 8px;
background: #f8fafc;
border-radius: 8px;
border: 1px dashed #e2e8f0;
}}
.stat-val-mini {{
font-size: 1.3rem;
font-weight: 800;
color: #1e293b;
}}
.stat-lbl-mini {{
font-size: 0.82rem;
color: #64748b;
font-weight: 600;
text-transform: uppercase;
}}
</style>
<div class="accuracy-container">
<div style="display: flex; justify-content: space-between; align-items: center;">
<span style="font-size: 1.0rem; font-weight: 700; color: #334155;">Answer Accuracy Breakdown</span>
<span style="font-size: 0.95rem; font-weight: 800; color: #10b981;">{correct_percent:.1f}% Correct</span>
</div>
<div class="accuracy-bar-wrapper">
{"<div class='accuracy-bar-correct'>" + f"{total_correct} Correct</div>" if correct_percent > 0 else ""}
{"<div class='accuracy-bar-incorrect'>" + f"{total_incorrect} Incorrect</div>" if incorrect_percent > 0 else ""}
{"" if total_questions > 0 else "<div style='width: 100%; color: #94a3b8; font-size: 0.85rem; line-height: 24px; text-align: center; font-style: italic;'>No answers recorded yet</div>"}
</div>
<div class="stat-grid-mini">
<div class="stat-item-mini">
<div class="stat-val-mini">🎯 {total_quizzes}</div>
<div class="stat-lbl-mini">Total Quizzes</div>
</div>
<div class="stat-item-mini">
<div class="stat-val-mini">⚡ {pref_difficulty}</div>
<div class="stat-lbl-mini">Preferred Diff</div>
</div>
<div class="stat-item-mini">
<div class="stat-val-mini">⏱️ {avg_duration}s</div>
<div class="stat-lbl-mini">Avg Duration</div>
</div>
</div>
</div>""", unsafe_allow_html=True)
                    
                    st.markdown(f"""<div style="display: flex; gap: 15px; margin-top: 10px;">
<div style="flex: 1; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 12px; text-align: center;">
<div style="font-size: 0.85rem; color: #64748b; font-weight: 600;">Average Score</div>
<div style="font-size: 1.35rem; font-weight: 800; color: #4f46e5;">{avg_score:.1f}/{avg_total:.0f}</div>
</div>
<div style="flex: 1; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 12px; text-align: center;">
<div style="font-size: 0.85rem; color: #64748b; font-weight: 600;">Total Quiz XP</div>
<div style="font-size: 1.35rem; font-weight: 800; color: #8b5cf6;">{total_xp_earned} XP</div>
</div>
<div style="flex: 1; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 12px; text-align: center;">
<div style="font-size: 0.85rem; color: #64748b; font-weight: 600;">High / Low Score</div>
<div style="font-size: 1.35rem; font-weight: 800; color: #f59e0b;">{max(scores)} / {min(scores)}</div>
</div>
</div>""", unsafe_allow_html=True)
                    
                    st.markdown("<hr style='border: 0; border-top: 1px solid #e2e8f0; margin: 25px 0;'>", unsafe_allow_html=True)
                    st.markdown("<div style='font-size: 1.1rem; font-weight: 700; color: #475569; margin-bottom: 10px;'>🎯 Topic Mastery & Study Guide</div>", unsafe_allow_html=True)
                    
                    # Process wrong answers by topic_tag
                    topic_correct = {}
                    topic_total = {}
                    for att in history:
                        for ans in att.get("answers", []):
                            t_tag = ans.get("topic_tag", "General")
                            topic_total[t_tag] = topic_total.get(t_tag, 0) + 1
                            if ans.get("is_correct", False):
                                topic_correct[t_tag] = topic_correct.get(t_tag, 0) + 1
                                
                    topic_mastery = []
                    for t_tag in topic_total:
                        correct = topic_correct.get(t_tag, 0)
                        total = topic_total[t_tag]
                        mastery = (correct / total) * 100
                        topic_mastery.append({
                            "topic": t_tag,
                            "mastery": mastery,
                            "mistakes": total - correct
                        })
                        
                    # Sort by mastery ascending (weakest first)
                    topic_mastery.sort(key=lambda x: x["mastery"])
                    
                    weak_count = 0
                    weak_topics_to_show = [tm for tm in topic_mastery if tm["mastery"] < 80]
                    
                    if weak_topics_to_show:
                        num_cols = min(2, len(weak_topics_to_show))
                        weak_cols = st.columns(num_cols)
                        for idx_w, tm in enumerate(weak_topics_to_show[:2]):
                            with weak_cols[idx_w]:
                                st.markdown(f"""
                                    <div style="background: rgba(239, 68, 68, 0.04); border-left: 3px solid #ef4444; border-radius: 6px; padding: 8px 12px; margin-bottom: 8px; height: 100%;">
                                        <div style="font-size: 0.95rem; font-weight: 700; color: #ef4444;">⚠️ Weak Topic: {tm['topic']} ({tm['mastery']:.0f}% mastery)</div>
                                        <div style="font-size: 0.85rem; color: #64748b; margin-top: 3px;">Recommendation: Review related sections in the current document. Ask AI for detailed concept breakdown of '{tm['topic']}'.</div>
                                    </div>
                                """, unsafe_allow_html=True)
                                weak_count += 1
                                
                    if weak_count == 0:
                        st.success("🌟 Excellent! You have achieved >80% mastery in all topics. Keep maintaining this streak!", icon="✨")

                # 4. Quiz History List
                if history:
                    st.markdown("<div style='margin-top: 25px;'></div>", unsafe_allow_html=True)
                    st.markdown("#### 📚 Quiz History (Recent Attempts)")
                    
                    # Custom CSS to align elements nicely
                    st.markdown("""
                        <style>
                        .history-row {
                            display: flex;
                            align-items: center;
                            justify-content: space-between;
                            background: #ffffff;
                            border: 1px solid #e2e8f0;
                            border-radius: 10px;
                            padding: 10px 16px;
                            margin-bottom: 8px;
                        }
                        .history-meta {
                            font-size: 0.92rem;
                            color: #64748b;
                        }
                        .history-title {
                            font-size: 1.05rem;
                            font-weight: 700;
                            color: #1e293b;
                        }
                        .history-score {
                            font-size: 1.25rem;
                            font-weight: 800;
                            color: #4f46e5;
                        }
                        </style>
                    """, unsafe_allow_html=True)
                    
                    with st.container(height=350):
                        for idx_hist, att in enumerate(history):
                            att_id = att.get("attempt_id", "")
                            att_date = att.get("date", "")
                            try:
                                # Format date nicely
                                date_obj = datetime.fromisoformat(att_date.replace("Z", "+00:00"))
                                formatted_date = date_obj.strftime("%Y-%m-%d %H:%M")
                            except Exception:
                                formatted_date = att_date[:16].replace("T", " ")

                            att_topic = att.get("topic", "General")
                            att_difficulty = att.get("difficulty", "Medium")
                            att_score = att.get("score", 0)
                            att_total = att.get("total_questions", 10)
                            att_is_retry = att.get("is_retry", False)

                            retry_label = " (Retry)" if att_is_retry else ""

                            col_h1, col_h2, col_h3 = st.columns([5.0, 1.0, 3.0])
                            with col_h1:
                                st.markdown(f"""
                                    <div style='padding-top: 4px;'>
                                        <span class='history-title'>{att_topic}</span><span style='color: #6366f1; font-weight: 600; font-size: 0.9rem;'>{retry_label}</span>
                                        <div class='history-meta'>📅 {formatted_date} • 🎯 Difficulty: {att_difficulty}</div>
                                    </div>
                                """, unsafe_allow_html=True)
                            with col_h2:
                                st.markdown(f"""
                                    <div style='text-align: center; padding-top: 8px;'>
                                        <span class='history-score'>{att_score} / {att_total}</span>
                                    </div>
                                """, unsafe_allow_html=True)
                            with col_h3:
                                show_retry = (att_score < att_total)
                                if show_retry:
                                    btn_rev_col, btn_ret_col = st.columns(2)
                                    with btn_rev_col:
                                        if st.button("Review 🔍", key=f"rev_att_{att_id}", use_container_width=True):
                                            st.session_state.quiz_data = att.get("answers", [])
                                            st.session_state.review_mode = True
                                            st.session_state.quiz_mode_active = True
                                            st.session_state.current_q_index = 0
                                            st.session_state.quiz_finished = False
                                            st.session_state.is_retry = False
                                            st.session_state.quiz_difficulty = att_difficulty
                                            st.session_state.quiz_time_limit_minutes = 0
                                            st.session_state.quiz_timer_start = None
                                            st.rerun()
                                    with btn_ret_col:
                                        if st.button("Retry 💪", key=f"ret_att_{att_id}", use_container_width=True, type="primary"):
                                            # Filter wrong answers
                                            wrong_answers = [ans for ans in att.get("answers", []) if not ans.get("is_correct", False)]
                                            # Re-shuffle/strip prefixes to allow re-answering
                                            clean_wrong_answers = []
                                            for ans in wrong_answers:
                                                opts_stripped = []
                                                for opt in ans.get("options", []):
                                                    if len(opt) > 3 and opt[0].isalpha() and opt[1:3] == ". ":
                                                        opts_stripped.append(opt[3:])
                                                    else:
                                                        opts_stripped.append(opt)
                                                correct_ans_stripped = ans.get("correct_answer", "")
                                                if len(correct_ans_stripped) > 3 and correct_ans_stripped[0].isalpha() and correct_ans_stripped[1:3] == ". ":
                                                    correct_ans_stripped = correct_ans_stripped[3:]

                                                import random
                                                random.shuffle(opts_stripped)

                                                prefixed_en = []
                                                correct_ans_prefixed = correct_ans_stripped
                                                for idx_o, opt in enumerate(opts_stripped):
                                                    prefix = f"{chr(65+idx_o)}. "
                                                    prefixed_en.append(prefix + str(opt))
                                                    if str(opt) == str(correct_ans_stripped):
                                                        correct_ans_prefixed = prefix + str(opt)

                                                clean_wrong_answers.append({
                                                    "question": ans.get("question", ""),
                                                    "options": prefixed_en,
                                                    "correct_answer": correct_ans_prefixed,
                                                    "explanation": ans.get("explanation", ""),
                                                    "topic_tag": ans.get("topic_tag", "General")
                                                })

                                            st.session_state.quiz_data = clean_wrong_answers
                                            st.session_state.parent_attempt_id = att_id
                                            st.session_state.is_retry = True
                                            st.session_state.quiz_mode_active = True
                                            st.session_state.current_q_index = 0
                                            st.session_state.quiz_finished = False
                                            st.session_state.review_mode = False
                                            st.session_state.quiz_difficulty = att_difficulty
                                            st.session_state.quiz_time_limit_minutes = 0
                                            st.session_state.quiz_timer_start = time.time()

                                            for key in list(st.session_state.keys()):
                                                if key.startswith('user_ans_') or key.startswith('radio_q_') or key.startswith('q_submitted_'):
                                                    del st.session_state[key]
                                            st.rerun()
                                else:
                                    if st.button("Review 🔍", key=f"rev_att_{att_id}", use_container_width=True):
                                        st.session_state.quiz_data = att.get("answers", [])
                                        st.session_state.review_mode = True
                                        st.session_state.quiz_mode_active = True
                                        st.session_state.current_q_index = 0
                                        st.session_state.quiz_finished = False
                                        st.session_state.is_retry = False
                                        st.session_state.quiz_difficulty = att_difficulty
                                        st.session_state.quiz_time_limit_minutes = 0
                                        st.session_state.quiz_timer_start = None
                                        st.rerun()

        st.markdown("<br>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
