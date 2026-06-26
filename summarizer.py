import time

import google.generativeai as genai  # type: ignore
from google.api_core import exceptions  # type: ignore

def _get_model_name(api_key):
    """
    Helper to find an available Gemini model.
    """
    try:
        genai.configure(api_key=api_key)
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        preferences = [
            'models/gemini-2.5-flash-lite',
            'models/gemini-flash-lite-latest',
            'models/gemini-flash-latest',
            'models/gemini-1.5-flash',
            'models/gemini-1.5-pro'
        ]

        for pref in preferences:
            if pref in available_models:
                return pref

        if available_models:
            return available_models[0]
    except Exception as e:
        print(f"Model selection helper failed: {e}")

    return 'gemini-1.5-flash'  # Final fallback

def _generate_with_retry(model, prompt, max_retries=3):
    """
    Wrapper to handle 429 Too Many Requests (Rate Limits) with exponential backoff.
    """
    base_delay = 15
    for attempt in range(max_retries):
        try:
            return model.generate_content(prompt)
        except Exception as e:
            error_msg = str(e)
            # Check for 429 or quota exceeded
            if "429" in error_msg or "Quota exceeded" in error_msg:
                if attempt < max_retries - 1:
                    sleep_time = base_delay * (2 ** attempt)
                    print(f"Rate limited (429). Retrying in {sleep_time} seconds (Attempt {attempt + 1}/{max_retries})...")
                    time.sleep(sleep_time)
                    continue
            # If it's not a rate limit or we're out of retries, raise it
            raise

def summarize_text(raw_text, api_key):
    """
    Cleans and summarizes raw text using Google's Gemini LLM.

    Args:
        raw_text (str): The raw text extracted from OCR (may contain errors).
        api_key (str): Google AI Studio API Key provided by the user.

    Returns:
        str: The generated summary in Markdown format.
    """
    if not api_key:
        return "⚠️ Error: Please provide a Google API Key in the sidebar."

    if not raw_text.strip():
        return "⚠️ Error: No text found to analyze."

    # Configure the API key
    try:
        genai.configure(api_key=api_key)
    except Exception as e:
        return f"⚠️ Configuration Error: {str(e)}"

    system_prompt = """
    You are an expert technical editor and document analysis assistant. Your goal is to process OCR-extracted text, correct errors, and extract the most important insights regarding the core knowledge without being overly verbose.

    **Task 1: Clean (Internal Process)**
    Silently correct obvious OCR typos, garbled text, and formatting errors. Ensure technical terms and names are standardized. Maintain the original meaning. Do not output the full cleaned text.

    **Task 2: Extract Knowledge Core (CRITICAL)**
    Analyze the cleaned text thoroughly. STRICTLY filter out any irrelevant fluff, such as speaker/teacher self-introductions, chit-chat, administrative nonsense, or tangential remarks. Focus ONLY on the actual educational knowledge content, core concepts, methodologies, and learning focal points.

    **Task 3: Format**
    You MUST strictly output your final response using the exact Markdown text structure provided below (in ENGLISH). DO NOT output JSON. DO NOT use JSON objects or strings. Output standard Markdown formatting ONLY. Do not add introductory or concluding remarks outside of this structure.

    # Core Knowledge Overview
    (Write a clear, professional 1-3 paragraph summary of the core knowledge, main academic or technical topics, and primary learning objectives. Strictly exclude any introductions, pleasantries, or irrelevant administrative details.)

    # Key Learning Points
    (Provide a focused list of 4-6 highly detailed bullet points representing the critical knowledge takeaways, concepts, or methodologies. Each point should be 1-2 complete sentences explaining the specific academic or technical insight.)
    * [Point 1]
    * [Point 2]
    * [Point 3]
    * [Point 4]
    """

    full_prompt = f"{system_prompt}\n\nHere is the raw text extracted by OCR, please process it:\n\n{raw_text}"

    try:
        model_name = _get_model_name(api_key)
        model = genai.GenerativeModel(model_name)
        response = _generate_with_retry(model, full_prompt)
        return response.text
    except exceptions.GoogleAPICallError as e:
        return f"⚠️ Google API Error: {str(e)}"
    except ValueError as e:
        # Often happens if the response was blocked by safety settings
        return f"⚠️ Error: content generation failed (possibly safety block). Details: {str(e)}"
    except Exception as e:
        return f"⚠️ Unexpected Error: {str(e)}"

def translate_text(text, api_key, target_language="Chinese"):
    """
    Translates the given text into the target language using Gemini.
    """
    if not api_key:
        return "⚠️ Error: API Key missing."
    if not text.strip():
        return ""

    try:
        model_name = _get_model_name(api_key)
        model = genai.GenerativeModel(model_name)

        prompt = f"""
        You are a professional translator. Translate the following Markdown text into {target_language}.
        Maintain the Markdown formatting, headers, and structure exactly as provided.
        Only output the translated text. Do not add any preamble or meta-comments.

        Text to translate:
        {text}
        """

        response = _generate_with_retry(model, prompt)
        return response.text
    except Exception as e:
        return f"⚠️ Translation Error: {str(e)}"

def test_api_connection(api_key):
    """
    Tests the API key by listing available models.
    """
    if not api_key:
        return False, "API Key is empty."

    try:
        genai.configure(api_key=api_key)
        # Try to list models (limit to 1 to check auth)
        msg = "Successfully connected! Available models:\n"
        count = 0
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                if count < 5:  # List first 5
                    msg += f"- {m.name}\n"
                count += 1
        return True, msg
    except Exception as e:
        return False, str(e)

def generate_quiz(text, api_key, target_language="Chinese", difficulty="Medium"):
    """
    Generates a 10-question JSON quiz based on the document text.
    """
    if not api_key:
        return None, "⚠️ Error: API Key missing."
    if not text.strip():
        return None, "⚠️ Error: No text found to analyze."

    try:
        model_name = _get_model_name(api_key)
        model = genai.GenerativeModel(model_name)

        prompt = f"""You are an expert online education quiz creator. Based on the provided document content, generate 10 multiple-choice questions.

Difficulty Level: {difficulty}
For this difficulty:
- Easy: Focus on simple direct recall of facts, definitions, and basic concepts. Distractor options should be clearly incorrect. Options should be short and simple.
- Medium: Focus on conceptual understanding, identifying relationships, applying concepts, and standard academic check questions.
- Hard: Focus on advanced synthesis, logical proofs, mathematical reasoning, debugging, or analyzing complex scenarios. Questions should require deep thinking and distractor options should be plausible and challenging.

[IMPORTANT: Strict Output Format Requirements]
Your output MUST be a strict, valid JSON array structure. Do NOT include any Markdown formatting markers (such as ```json), do NOT place the JSON inside a code block, and do NOT output any preamble, postamble, or chain-of-thought analysis. Only output the raw JSON string directly!

The JSON structure MUST perfectly match the following example format, containing BOTH English and {target_language} translations, and a specific "topic_tag" metadata tag for each question:
[
  {{
    "question": "What is the specific question?",
    "question_trans": "Translation of the question in exactly {target_language}",
    "options": [
      "Content of the first option",
      "Content of the second option",
      "Content of the third option",
      "Content of the fourth option"
    ],
    "options_trans": [
      "Translation of option 1 in {target_language}",
      "Translation of option 2 in {target_language}",
      "Translation of option 3 in {target_language}",
      "Translation of option 4 in {target_language}"
    ],
    "correct_answer": "Content of the first option",
    "explanation": "The reason why this option is correct and a detailed explanation of the related knowledge point.",
    "explanation_trans": "Translation of the detailed explanation in {target_language}.",
    "topic_tag": "A brief sub-concept tag (e.g. 'Base Cases', 'Inductive Hypothesis', 'Algebraic Simplification')"
  }}
]

[Constraints]
1. You MUST generate exactly 10 questions.
2. Each question MUST have exactly 4 options. DO NOT include prefixes like "A.", "B.", "C.", "D." in the options.
3. The value of `correct_answer` MUST exactly match one of the items in the `options` array (word for word in English).
4. All `_trans` keys MUST contain high-quality, natural-sounding {target_language} translations of their English counterparts.
5. CRITICAL: DO NOT always make the first option the correct answer. You MUST randomly vary the position of the correct answer among the 4 options for each question.
6. CRITICAL: The output must be strictly valid JSON. Escape all backslashes as double-backslashes (e.g. use \\\\ instead of \\) and ensure there are no unescaped control characters (like raw newlines or tabs) inside string values.
7. Tag each question with an appropriate, short "topic_tag" based on the specific concept being tested, so we can analyze weak areas.

Document Content:
{text}"""

        response = _generate_with_retry(model, prompt)
        return response.text, None
    except Exception as e:
        return None, f"⚠️ Quiz Generation Error: {str(e)}"

def generate_mindmap(summary_text, api_key, target_language="English"):
    """
    Generates a hierarchical Markdown list based on the summary, optimized for mindmap rendering.
    """
    if not api_key:
        return "# Error\n- API Key missing."
    if not summary_text.strip():
        return "# Error\n- No content."

    try:
        genai.configure(api_key=api_key)
    except Exception as e:
        return f"# Error\n- Configuration failed: {str(e)}"

    prompt = f"""You are an expert information architect and mindmap designer. Your task is to convert the following document summary into a highly structured, hierarchical Markdown list optimized for rendering as a mindmap (using markmap).

[Formatting Rules]
1. Start with a single `#` header for the main central topic of the mindmap. Keep it very short (1-4 words).
2. Use `##` headers for the primary branches (sub-topics/key categories). Keep them short (1-3 words).
3. Use `###` headers or bullet points (`-`) for secondary branches or supporting details.
4. Keep every node name extremely concise (1-5 words). DO NOT write long sentences, descriptions, or paragraphs. Avoid verbose text.
5. Do NOT use markdown styling like bold (`**`), italics (`*`), or inline code (` ` `) inside node labels.
6. The output must contain ONLY the valid Markdown list structure. Do NOT wrap the output in markdown code blocks like ```markdown and do NOT write any introductory or concluding text.
7. You MUST write the mindmap nodes in the requested language: {target_language}.

Summary Content:
{summary_text}"""

    try:
        model_name = _get_model_name(api_key)
        model = genai.GenerativeModel(model_name)
        response = _generate_with_retry(model, prompt)
        
        # Clean up any markdown code block wrapping if LLM outputted it
        text = response.text.strip()
        if text.startswith("```markdown"):
            text = text[11:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()
    except Exception as e:
        return f"# Error\n- Generation failed: {str(e)}"

def generate_chat_response(ocr_text, summary_text, chat_history, user_question, api_key, quiz_context=""):
    """
    Generates a response from the DocuMind AI Learning Assistant based on
    OCR text, summary, chat history, the current question, and optional quiz context.
    """
    if not api_key:
        return "⚠️ Error: API Key missing."
        
    try:
        genai.configure(api_key=api_key)
    except Exception as e:
        return f"⚠️ Configuration Error: {str(e)}"
        
    formatted_history = ""
    for msg in chat_history:
        role_label = "User" if msg["role"] == "user" else "Assistant"
        formatted_history += f"{role_label}: {msg['content']}\n"
        
    system_prompt = """You are DocuMind AI Learning Assistant. Your role is to help students understand learning materials, lecture notes, quiz questions, and educational content.

=== CRITICAL RULES ===

1. SOURCE SELECTION PRIORITY:
   Before generating any answer, determine the correct content source in this exact order:
   - Priority 1: Current User Message (if the user provides text directly in their query).
   - Priority 2: Most Recent Assistant Response (from the context).
   - Priority 3: Most Recent User Message.
   - Priority 4: Full Conversation History (for follow-up questions/clarifications).
   - Priority 5: OCR Extracted Text (uploaded notes).
   - Priority 6: Generated Summary of notes.
   Always choose the highest-priority valid source. Never automatically use OCR notes or summaries unless they are relevant to the user's request.

2. TRANSLATION RULES:
   If the user asks to translate (e.g., "translate", "翻译", "translate this", "translate the above content", "翻译以上内容"):
   - Identify the target using the Source Selection Priority (defaulting to the most recent assistant response if no text is in the current message).
   - Translate ONLY the target content. Do NOT explain, summarize, or search OCR notes.
   - If no target language is specified: translate English text to Chinese, and translate Chinese text to English.

3. SUMMARIZATION & REWRITE RULES:
   If the user asks to summarize, rewrite, paraphrase, or simplify:
   - Process ONLY the target content determined by the Source Selection Priority. Do NOT answer unrelated concepts or search OCR notes.

4. FOLLOW-UP & REFERENCE RULES:
   - Resolve pronouns ("it", "this", "above", "这个", "上面", "上述", "以上", "刚刚") automatically using the Source Selection Priority.
   - Apply follow-up requests (e.g., "explain more", "give example", "why is it important") to the most recent relevant content from the conversation history.

5. OCR & QUIZ RULES:
   - Use OCR notes or generated summaries ONLY when the user explicitly asks about the lecture notes (e.g., "Explain chapter 3", "Summarize notes").
   - Use quiz questions/answers context only when the user asks about the quiz (e.g., "Why is this answer wrong?").

6. LANGUAGE RULES:
   - Respond in the same language as the user (English -> English, Chinese -> Chinese, Malay -> Malay).

=== OUTPUT CONSTRAINT (CRITICAL) ===
- You MUST ONLY output the final response/result. 
- Do NOT output any decision steps, reasoning, planning logs, classification details, or intermediate thinking.
- Never output headers/bullets like "Step 1", "User Intent", "Content Source", "Selected Content", or "Final Decision Process".
- Failure to comply with this constraint is unacceptable. Output ONLY the clean final answer."""

    # Find most recent assistant response and user message for explicit prompt referencing
    most_recent_assistant = ""
    most_recent_user = ""
    for msg in reversed(chat_history):
        if msg["role"] == "assistant" and not most_recent_assistant:
            most_recent_assistant = msg["content"]
        if msg["role"] == "user" and not most_recent_user:
            most_recent_user = msg["content"]

    prompt = f"""=== CONTEXT SOURCES ===

1. OCR Extracted Text (uploaded lecture notes):
{ocr_text}

2. Generated Summary of the notes:
{summary_text}

3. Most Recent Assistant Response:
{most_recent_assistant}

4. Most Recent User Message:
{most_recent_user}

5. Full Conversation History:
{formatted_history}

{quiz_context}

=== CURRENT USER QUESTION ===
{user_question}
"""

    try:
        model_name = _get_model_name(api_key)
        model = genai.GenerativeModel(model_name, system_instruction=system_prompt)
        response = _generate_with_retry(model, prompt)
        return response.text
    except Exception as e:
        return f"⚠️ Chat Error: {str(e)}"

if __name__ == "__main__":
    pass
