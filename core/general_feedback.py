#core/general_feedback.py

from api_integration.gemini_api import GeminiAPI
from data.data_handler import load_prompt
from datetime import datetime
import re
import unicodedata
import json

gemini_api = GeminiAPI()

def normalize_text(text):
    """Remove accents and convert to lowercase"""
    # Normalize unicode characters
    normalized = unicodedata.normalize('NFKD', text)
    # Remove diacritics
    ascii_text = normalized.encode('ASCII', 'ignore').decode('ASCII')
    return ascii_text.lower().strip()

def parse_sections(feedback_text):
    """Parse the feedback text into structured sections"""
    # Dictionary to map normalized section names to expected keys
    section_mapping = {
        'perfil': 'summary',
        'summary': 'summary',
        'habilidades': 'skills',
        'skills': 'skills',
        'experiencia laboral': 'relevant_work_experience',
        'work experience': 'relevant_work_experience',
        'educacion': 'education',
        'education': 'education',
        'idiomas': 'languages',
        'languages': 'languages'
    }
    sections = {
        "email_intro": "",
        "summary": {
            "feedback": "",
            "example": ""
        },
        "skills": {
            "feedback": "",
            "example": ""
        },
        "relevant_work_experience": {
            "feedback": "",
            "example": ""
        },
        "education": {
            "feedback": "",
            "example": ""
        },
        "languages": {
            "feedback": "",
            "example": ""
        },
    }

    #Get the introduction (everything before 1st section)
    intro_match = re.match(r".*?(?=-\w+-)", feedback_text, re.DOTALL)
    if intro_match:
        sections["email_intro"] = intro_match.group(0).strip()

    # Find all sections
    section_pattern = r"-\s*([^-]+?)\s*-\s*\n+\s*(.*?)(?=(?:-[^-]+-|\n\n¡|$))" #r"-([^-]+)-\n\n(.*?)(?=(?:-[^-]+-|\n\n¡|$))" 
                      
    section_matches = re.finditer(section_pattern, feedback_text, re.DOTALL)

    for match in section_matches:
        section_name = match.group(1).lower().replace(" ", "_")
        content = match.group(2).strip()

        #Split feedback and example
        example_pattern = r"Aquí te presento un ejemplo.*?(?:[:]\s*|\n\n)"
        parts = re.split(example_pattern, content, maxsplit = 1)

        if section_name in sections:
            sections[section_name]["feedback"] = parts[0].strip()
            if len(parts) > 1:
                sections[section_name]["example"] = parts[1].strip()    
    
    return sections

def general_analyzer(resume_dict):
    try:
        # Extract relevant sections from the dictionary
        first_name = resume_dict["user_info"]["first_name"]
        
        # Convert to string if it's not already a string
        first_name = str(first_name) if not isinstance(first_name, str) else first_name

        # Structure the prompt to request a structured JSON response
        prompt_content = load_prompt("entire_resume_analyzer_prompt_v6.txt")
        
        # Format the prompt with the user's data
        formatted_prompt = prompt_content.format(
            first_name=first_name.title(),
            Summary=resume_dict["summary"],
            Skills=resume_dict["skills"],
            Work_Experience=json.dumps(resume_dict["relevant_work_experience"]),  # Properly serialize to JSON
            Education=resume_dict["education"],
            Languages=resume_dict["languages"],
        )
        
        # Get feedback from Gemini
        feedback_response = gemini_api.generate_content(formatted_prompt)

        try:
            # Clean the response text
            response_text = str(feedback_response).strip()
            if response_text.startswith("```json"):
                response_text = response_text.replace("```json", "", 1)
            if response_text.endswith("```"):
                response_text = response_text.rsplit("```", 1)[0]
            
            # Remove any leading/trailing whitespace and quotes
            response_text = response_text.strip('"\' \n\t')
            
            # Parse the JSON response
            feedback_dict = json.loads(response_text)
            
            # Create the structure for the dictionary
            structured_feedback = {
                'general_feedback': feedback_dict,
                'feedback_made_timestamp': datetime.now().isoformat()
            }
            
            if feedback_response:
                resume_dict.update(structured_feedback)
            
            print("Added feedback to resume data.\n")
            return structured_feedback
            
        except json.JSONDecodeError as json_err:
            print(f"JSON parsing error: {json_err}")
            print(f"Attempted to parse: {response_text}")
            return {
                'error': f"Failed to parse Gemini response as JSON: {str(json_err)}",
                'raw_response': str(feedback_response),
                'analysis_timestamp': datetime.now().isoformat()
            }
    except Exception as e:
        print(f"Error in general analyzer: {e}")
        return {
            'error': str(e),
            'analysis_timestamp': datetime.now().isoformat()
        }
    
def general_analyzer_df(first_name, candidate_data, skills, experience, education, languages):
    """Analyze resume data from dataframes and generate feedback
    
    Args:
        first_name (str): Candidate's first name
        candidate_data (DataFrame): Candidate's general information
        skills (DataFrame): Candidate's skills
        experience (DataFrame): Candidate's work experience
        education (DataFrame): Candidate's education
        languages (DataFrame): Candidate's languages
        
    Returns:
        dict: Structured feedback for the candidate
    """
    try:
        # Format skills as separate lists for hard and soft skills
        hard_skills_list = skills['hard_skills'].tolist() if 'hard_skills' in skills.columns and not skills.empty else []
        soft_skills_list = skills['soft_skills'].tolist() if 'soft_skills' in skills.columns and not skills.empty else []
        
        # Format work experience as a list of dictionaries
        work_experience = []
        if not experience.empty:
            # Sort by start_date in descending order
            experience_sorted = experience.sort_values('start_date', ascending=False)
            
            for _, row in experience_sorted.iterrows():
                exp = {
                    'job_title': row['title'],
                    'company': row['company'],
                    'start_date': row['start_date'],
                    'end_date': row['end_date'],
                    'description': row['description'],
                    'location': row['location']
                }
                work_experience.append(exp)
        
        # Format education as a list of dictionaries
        education_list = []
        if not education.empty:
            # Sort by graduation_date in descending order
            education_sorted = education.sort_values('start_date', ascending=False)
            
            for _, row in education_sorted.iterrows():
                edu = {
                    'title': row['title'],
                    'institution': row['institution'],
                    'type': row['type'],
                    'start_date': row['start_date'],
                    'end_date': row['end_date'],
                    'notes': row['notes'],
                }
                education_list.append(edu)
        
        # Format languages as a list
        languages_list = languages['language'].tolist() if not languages.empty else []
        
        # Get summary if available
        summary = candidate_data['summary'].iloc[0] if 'summary' in candidate_data.columns else ""
        
        # Structure the prompt to request a structured JSON response
        prompt_content = load_prompt("entire_resume_analyzer_prompt_v7.txt")

        # Convert to string if it's not already a string
        first_name = str(first_name) if not isinstance(first_name, str) else first_name
        
        # Format the prompt with the user's data
        formatted_prompt = prompt_content.format(
            first_name=first_name.title(),
            Summary=summary,
            Hard_Skills=json.dumps(hard_skills_list),
            Soft_Skills=json.dumps(soft_skills_list),
            Work_Experience=json.dumps(work_experience),
            Education=json.dumps(education_list),
            Languages=", ".join(languages_list),
        )
        
        # Get feedback from Gemini
        feedback_response = gemini_api.generate_content(formatted_prompt)

        try:
            # Clean the response text
            response_text = str(feedback_response).strip()
            if response_text.startswith("```json"):
                response_text = response_text.replace("```json", "", 1)
            if response_text.endswith("```"):
                response_text = response_text.rsplit("```", 1)[0]
            
            # Remove any leading/trailing whitespace and quotes
            response_text = response_text.strip('"\' \n\t')
            
            # Parse the JSON response
            feedback_dict = json.loads(response_text)
            
            # Create the structure for the dictionary
            structured_feedback = {
                'general_feedback': feedback_dict,
                'feedback_made_timestamp': datetime.now().isoformat()
            }

            print("Generated feedback successfully.\n")
            return structured_feedback
            
        except json.JSONDecodeError as json_err:
            print(f"JSON parsing error: {json_err}")
            print(f"Attempted to parse: {response_text}")
            return {
                'error': f"Failed to parse Gemini response as JSON: {str(json_err)}",
                'raw_response': str(feedback_response),
                'analysis_timestamp': datetime.now().isoformat()
            }
    except Exception as e:
        print(f"Error in general analyzer: {e}")
        return {
            'error': str(e),
            'analysis_timestamp': datetime.now().isoformat()
        }