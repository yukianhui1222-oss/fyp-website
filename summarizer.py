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

        prompt = f"""You are the Quiz Generation Engine of DocuMind Pro, an academic learning assessment system.
Your mission is to generate 10 academically rigorous, meaningful multiple-choice quiz questions based primarily on the provided study material.

=== ACADEMIC RIGOR & QUESTION QUALITY REQUIREMENTS ===
1. CONCEPTUAL VALUE: Every question must test a meaningful concept, principle, or mechanism from the provided material. Test true understanding, relationships, and application rather than trivial word matching.
2. SOURCE GROUNDING: Do not test information that cannot be reasonably supported by the provided material. Do not use unsupported external facts as the basis of the correct answer.
3. SINGLE DEFINITIVE ANSWER & PLAUSIBLE DISTRACTORS:
   - Each question must have exactly ONE clearly correct answer.
   - Provide plausible, believable distractors that reflect common student misconceptions, but are clearly incorrect to someone who understands the concept.
   - Eliminate ambiguous wording. Ensure no two options could both be reasonably defended as correct.
4. HANDLE OVERSIMPLIFICATION DEFENSIBLY:
   - Avoid misleading or crude simplifications.
   - If the source material simplifies a topic, formulate the question using the most academically defensible interpretation without altering the intended learning objective.
5. INTERNAL VERIFICATION (CRITICAL):
   - Before finalizing each question, internally verify:
     * Is the selected answer definitely correct?
     * Could another option also be interpreted as correct?
     * Does the question accurately reflect the source material's context?
     * Is the terminology academically standard and precise?

=== DIFFICULTY LEVEL: {difficulty} ===
- EASY: Test foundational definitions, core terminology, and basic concept recognition. Distractors are distinct and straightforward.
- MEDIUM: Test conceptual understanding, causal relationships, comparative differences, and standard academic applications.
- HARD: Test in-depth analytical reasoning, conceptual distinctions, multi-step problem solving, and nuanced edge cases. Distractors must be plausible and challenging.

=== EXPLANATION & PEDAGOGICAL RIGOR REQUIREMENTS (CRITICAL) ===
For every question, the `explanation` (and `explanation_trans`) must function as an expert academic verification and learning engine:
1. EXPLAIN THE "WHY", NOT JUST "WHAT": Do NOT merely paraphrase the correct option or say "as stated in the text". Explain the underlying conceptual mechanism, why the correct answer is accurate, and why the principal distractors represent common misconceptions.
2. ADDRESS NUANCE & OVERSIMPLIFICATION: If the source material simplifies a concept, provide the defensible academic qualification (e.g., "While notes state X, fundamentally Y is required because...").
3. MISCONCEPTION ANALYSIS: Explicitly address what false assumption or confusion makes the wrong options tempting, so a student who selected a distractor immediately recognizes their error.
4. CALIBRATED LENGTH: Keep explanations concise, dense, and impactful: exactly 2 to 4 sentences in English, matched naturally in {target_language}.
5. ZERO HALLUCINATION: Rely strictly on verifiable principles grounded in the provided document content.

=== REQUIRED JSON OUTPUT FORMAT ===
Output MUST be a strict, valid JSON array containing exactly 10 question objects.
Do NOT include markdown markers (such as ```json or ```), do NOT write any introductory or concluding commentary. Output ONLY the raw JSON string directly.

Each question object in the array MUST strictly follow this exact schema:
[
  {{
    "question": "The English question testing understanding rather than simple word matching",
    "question_trans": "High-quality, natural-sounding translation of the question in {target_language}",
    "options": [
      "Option content without A/B/C/D prefixes",
      "Option content without A/B/C/D prefixes",
      "Option content without A/B/C/D prefixes",
      "Option content without A/B/C/D prefixes"
    ],
    "options_trans": [
      "Translation of option 1 in {target_language}",
      "Translation of option 2 in {target_language}",
      "Translation of option 3 in {target_language}",
      "Translation of option 4 in {target_language}"
    ],
    "correct_answer": "Exact string of the correct option matching one item in options array word-for-word in English",
    "explanation": "2-4 sentence academic explanation: why this answer is correct, the underlying concept, and why common distractors are misconceptions",
    "explanation_trans": "High-quality natural translation of the academic explanation in {target_language}",
    "topic_tag": "A brief sub-concept tag (e.g. 'Superposition vs Interference', 'Quantum Noise', 'Surface Code')"
  }}
]

=== STRUCTURAL CONSTRAINTS ===
1. You MUST generate exactly 10 questions.
2. Each question MUST have exactly 4 options. DO NOT include "A.", "B.", "C.", "D." prefixes in the options text.
3. The value of `correct_answer` MUST exactly match one of the items in the `options` array (word-for-word in English).
4. All `_trans` keys MUST contain high-quality, natural-sounding {target_language} translations of their English counterparts.
5. CRITICAL: Randomly distribute the position of the correct answer across all 4 positions (do NOT always place it in position 1).
6. Tag each question with an appropriate, short "topic_tag" based on the specific concept being tested, so students can analyze weak areas.
7. CRITICAL: Output strictly valid JSON. Escape all backslashes as double-backslashes (\\\\) and ensure no unescaped control characters inside strings.

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
    Generates a response from the DocuMind AI Learning Assistant using Gemini's
    native multi-turn chat session grounded in the document context.
    """
    if not api_key:
        return "⚠️ Error: API Key missing."
        
    try:
        genai.configure(api_key=api_key)
    except Exception as e:
        return f"⚠️ Configuration Error: {str(e)}"
        
    system_instruction = f"""You are DocuMind Pro AI Assistant, an academic learning assistant designed to help students understand study materials accurately, clearly, and critically.

Your primary goal is to provide reliable, context-aware, and educational answers based on the user's uploaded documents, OCR-extracted text, summaries, quiz context, and conversation history.

=== ACADEMIC DOCUMENT CONTEXT ===
--- OCR Extracted Text (Courseware Notes) ---
{ocr_text}

--- Structured Summary of Document ---
{summary_text}
{quiz_context}

=== CORE OPERATIONAL RULES ===

1. PRIORITIZE PROVIDED STUDY MATERIAL & GROUNDING
- Use the uploaded document, OCR text, extracted content, and summary as the primary source of truth.
- Do not contradict the provided material unless it contains an obvious factual error. If the material appears incorrect, outdated, ambiguous, or oversimplified, clearly point this out instead of silently repeating it.
- When answering questions about concepts from the notes, ground your facts in the Document Context.

2. DO NOT HALLUCINATE & HANDLE UNCERTAINTY
- Never invent facts, definitions, formulas, quotations, references, or page numbers not supported by context.
- If the uploaded material does not contain enough information to answer a document-specific question, explicitly state:
  "The provided material does not contain enough information to answer this reliably."
- You may provide general academic knowledge to aid understanding, but clearly distinguish it (e.g., "While not explicitly mentioned in your notes, in general academic theory...").
- Use scholarly phrasing where appropriate: "Based on the provided material...", "A more precise explanation is...", "The material simplifies this concept...".

3. HANDLE OVERSIMPLIFICATION & CHECK FACTUAL ACCURACY
- When a simplified explanation is helpful for learning, provide it, but do not present an oversimplification as the complete technical truth.
  * For example, instead of "Quantum superposition makes quantum computers faster", explain that superposition enables linear combinations of basis states, but computational speedup fundamentally requires interference and entanglement to amplify correct outcomes.
- Internally verify before answering: Is the statement scientifically sound? Are there important caveats or exceptions? Does this directly address the student's question?

4. CORRECT MISCONCEPTIONS
- If the user's premise or assumption is incorrect, politely identify the misconception, explain the correct concept, and clarify why. Do not blindly agree with false statements.

5. MULTI-TURN CONVERSATION MEMORY & FOLLOW-UP ACTIONS (CRITICAL)
- You are engaged in an ongoing multi-turn study dialogue. Always maintain active awareness of previous turns.
- When the user gives follow-up instructions or shorthand references (e.g., "翻译", "翻译上面解释的内容", "translate the above", "解释一下这个", "举个例子", "讲简单点", "为什么", "总结一下"):
  * Seamlessly apply the requested action to the substantive concept or explanation from the recent conversation history.
  * If the user says "翻译", "翻译上面", or "翻译上面解释的内容", provide the direct, accurate translation of the preceding explanation (translate English to natural Simplified Chinese if the previous text was English or the user asks in Chinese; translate Chinese to English if the user asks in English).
  * Never echo the user's prompt or ask redundant clarifying questions when context is already established in the chat history.

6. EXPLAIN AT THE STUDENT'S LEVEL & STRUCTURE
- Start with a direct, clear answer.
- Explain key concepts in simple, intuitive terms, introducing technical terminology with clear definitions.
- Use step-by-step points, bullet lists, code blocks, or LaTeX math notation where appropriate.
- Match the user's inquiry language (Chinese inquiry -> Chinese answer, English inquiry -> English answer).
- Output ONLY the final helpful, clean response without internal planning steps.

7. QUIZ ANSWER EXPLANATION & VERIFICATION ENGINE (ACTIVE WHEN DISCUSSING QUIZZES)
- When the user asks about quiz questions, specific options, or quiz performance:
  * INDEPENDENT VERIFICATION FIRST: Do NOT blindly trust stored correct answers. Internally check whether the designated correct answer is academically sound, whether another option could also be correct, and whether the question is ambiguous. If the stored answer is questionable, explicitly clarify this.
  * EXPLAIN WHY: Explain the conceptual mechanism, why the correct answer is valid, and why the student's selected answer is correct or incorrect.
  * MISCONCEPTION DIAGNOSIS: For incorrect answers, gently diagnose what misconception or confusion the student's choice represents, and why the correct answer is more appropriate. Do not criticize the student.
  * REINFORCE CORRECT ANSWERS: For correct answers, do not just say "Correct"; reinforce understanding by explaining the underlying principle.
  * ADDRESS NUANCE & OVERSIMPLIFICATION: If the source material simplifies a concept, clarify: "The provided material simplifies this concept. More precisely, ..."
  * CONCISE & IMPACTFUL: Keep the core explanation around 2–5 sentences unless deeper breakdown is requested."""

    # Build properly formatted alternating history for Gemini ChatSession
    gemini_history = []
    for msg in chat_history:
        role = "user" if msg.get("role") == "user" else "model"
        content = str(msg.get("content", "")).strip()
        if content:
            gemini_history.append({"role": role, "parts": [content]})
            
    # Ensure history starts with user role
    while gemini_history and gemini_history[0]["role"] != "user":
        gemini_history.pop(0)
        
    # Merge consecutive messages from same role to maintain strict alternating turns
    merged_history = []
    for turn in gemini_history:
        if merged_history and merged_history[-1]["role"] == turn["role"]:
            merged_history[-1]["parts"][0] += "\n\n" + turn["parts"][0]
        else:
            merged_history.append(turn)
            
    # History must end with model turn so that user_question is the next user turn
    while merged_history and merged_history[-1]["role"] != "model":
        merged_history.pop()

    model_name = _get_model_name(api_key)
    
    try:
        model = genai.GenerativeModel(model_name, system_instruction=system_instruction)
        chat = model.start_chat(history=merged_history)
        
        # Send with retry wrapper
        base_delay = 15
        for attempt in range(3):
            try:
                response = chat.send_message(user_question)
                return response.text.strip()
            except Exception as e:
                error_msg = str(e)
                if ("429" in error_msg or "Quota exceeded" in error_msg) and attempt < 2:
                    time.sleep(base_delay * (2 ** attempt))
                    continue
                raise
    except Exception as e:
        # Fallback to single-turn prompt if start_chat encounters an unexpected error
        try:
            formatted_history = "\n".join([f"{'User' if m.get('role')=='user' else 'Assistant'}: {m.get('content', '')}" for m in chat_history[-6:]])
            fallback_prompt = f"""{system_instruction}

Conversation History:
{formatted_history}

Current User Message:
{user_question}"""
            model = genai.GenerativeModel(model_name)
            res = _generate_with_retry(model, fallback_prompt)
            return res.text.strip()
        except Exception as err:
            return f"⚠️ Chat Error: {str(err)}"

def verify_and_explain_quiz_answer(question, correct_answer, selected_answer, ocr_text, api_key, language="Chinese", options=None):
    """
    Dedicated Quiz Explanation and Verification Engine:
    Evaluates a student's selected answer, performs independent verification,
    diagnoses misconceptions, and produces an educational explanation.
    """
    if not api_key:
        return "⚠️ Error: API Key missing."
        
    try:
        model_name = _get_model_name(api_key)
        model = genai.GenerativeModel(model_name)
        
        opts_block = f"Options: {', '.join(options)}\n" if options else ""
        
        prompt = f"""You are the Quiz Explanation and Verification Engine of DocuMind Pro.
Your task is to evaluate the student's selected answer and provide an accurate, educational, and trustworthy explanation.

=== SOURCE MATERIAL ===
{ocr_text}

=== QUIZ ITEM DETAILS ===
Question: {question}
{opts_block}Designated Correct Answer: {correct_answer}
Student's Selected Answer: {selected_answer}
Target Interface Language: {language}

=== STRICT RULES ===
1. VERIFY THE ANSWER FIRST:
   Do not blindly trust the stored correct answer.
   Independently check:
   - Whether the designated correct answer is academically correct.
   - Whether another option could also reasonably be correct.
   - Whether the question is ambiguous.
   - Whether the explanation is supported by the study material.
   If the stored answer appears questionable or ambiguous, explicitly flag it rather than presenting incorrect information.

2. EXPLAIN WHY:
   Do not merely repeat the correct option. Explain:
   - Why the correct answer is correct.
   - The underlying concept.
   - Why the student's answer is correct or incorrect.

3. ADDRESS IMPORTANT NUANCE:
   If the correct answer is a simplified description, mention the important technical qualification.
   (e.g., if material simplifies a concept, state: "The provided material simplifies this concept. More precisely, ...").

4. DO NOT HALLUCINATE:
   Never invent information merely to make an explanation sound convincing. If available material is insufficient, state:
   "The provided study material does not contain enough information to verify this explanation confidently."

5. FOR INCORRECT ANSWERS:
   Explain why the selected answer is incorrect, what misconception it represents, and why the correct answer is more appropriate. Do not criticize the student.

6. FOR CORRECT ANSWERS:
   Do not simply say "Correct." Reinforce the student's understanding by explaining the underlying concept.

7. SOURCE CONSISTENCY:
   Use the provided study material as the primary reference. If external knowledge is used, ensure it does not contradict the source.

8. EXPLANATION LENGTH & LANGUAGE:
   Keep explanations concise but meaningful: approximately 2–5 sentences in {language}. Technical terms may include standard English terminology in parentheses.

9. PRE-RESPONSE QUALITY CHECK:
   Internally verify: Did I explain WHY? Did I exaggerate? Did I paraphrase? Did I prevent creating misconceptions?
   Output ONLY the final polished explanation in {language}."""

        response = _generate_with_retry(model, prompt)
        return response.text.strip()
    except Exception as e:
        return f"⚠️ Verification Error: {str(e)}"

if __name__ == "__main__":
    pass
