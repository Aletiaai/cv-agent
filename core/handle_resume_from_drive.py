#core/handle_resume_from_drive.py
import os.path
import uuid
import time
import io
import json
import traceback
import pandas as pd
from api_integration.gemini_api import GeminiAPI

import traceback
import pandas as pd

from datetime import datetime
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
from api_integration.drive_api import authenticate_drive_api
from data.data_handler import load_data, save_data, format_work_experience, get_candidate_feedback
from core.information_extractor import get_resume_text_from_pdf, extract_information
from core.handle_resume_from_email import send_feedback_email_2
from core.general_feedback import general_analyzer, general_analyzer_df
from core.asking_questions import complementary_questions
from temporal.temporal import ResumeProcessor

gemini_api = GeminiAPI()

service = authenticate_drive_api()

def get_folder_id(folder_path):
    """Gets the ID of a folder by its full path in Google Drive.
        Args: Folder_path: The path to the folder (e.g., "Parent Folder/Subfolder/Target Folder").
        Returns: The ID of the target folder (or None if not found).
    """
    parent_id = 'root'  # Start at the root of the Drive
    folder_names = folder_path.split('/')

    for folder_name in folder_names:
        try:
            query = f"name='{folder_name}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder'"
            results = service.files().list(
                q=query,
                fields="files(id)"
            ).execute()
            items = results.get('files', [])
            if not items:
                print(f"Could not find folder: {folder_name}")
                return None  # Folder not found at this level
            parent_id = items[0]['id']  # Update parent_id for the next level
        except HttpError as error:
            print(f"An error occurred: {error}")
            return None

    return parent_id  # This is the ID of the final folder in the path
    
def list_files_in_folder(folder_id):
    """Lists the files in a given folder.
    Args: Folder_id: The ID of the folder.
    Returns: A list of file objects (or [] if an error occurs).
    """
    try:
        results = service.files().list(
            q = f"'{folder_id}' in parents",
            fields = "files(id, name)"
        ).execute()
        items = results.get('files', [])
        return items
    except HttpError as e:
        print(f"An error in listing the files in folder ocurred: {e}")
        return []

def download_file(file_id, file_name, download_dir = "data/user_resumes_drive"):
    """Downloads a file from Google Drive.
    Args:
        file_id: The ID of the file to download.
        file_name: The name of the file.
        download_dir: The directory to save the file to.
    """
    try:
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)
        request = service.files().get_media(fileId = file_id)
        file_path = os.path.join(download_dir, file_name)

        with io.FileIO(file_path, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            print(f"Download {int(status.progress() * 100)}%.")
        print(f"file '{file_name}' downloaded to '{file_path}'")
    except HttpError as e:
        print(f"An error occurren while downloading the file {file_name}: {e}")

def number_files_in_drive(drive_folder_id):
    try:
        files = list_files_in_folder(drive_folder_id)
        if not files:
            print("No files found in the Google Drive folder.")

        total_files = len(files)
        return files, total_files
    
    except Exception as e:
            print(f"An error occurred when processing de number of files at folder id: {drive_folder_id} from Drive: {str(e)}")
            return None

def process_resume_from_drive(file_name, file_id):
    """Processes resumes from a Google Drive folder.
    Args: file_id: The ID of the file being processed.
        file_name: The name of the file being processed.
    """
    # check if the file is a pdf 
    if file_name.lower().endswith(".pdf"):
        print(f"Processing PDF file {file_name}")
        # Initialize fresh resume_array for each file
        resume_array = load_data()
        print(f"Downloading file: {file_name} (ID: {file_id})")
        download_file(file_id, file_name, download_dir="data/user_resumes_drive")
        resume_path = os.path.join("data/user_resumes_drive", file_name)    

        try:
            resume_text = get_resume_text_from_pdf(resume_path)
            if resume_text:
                # Generate a new UUID for CandidateID
                candidate_id = str(uuid.uuid4())
                resume_array["CandidateID"] = candidate_id
                resume_array["file_path"] = resume_path
                resume_array["resume_text"] = resume_text

                #Extract information from resume in one API call
                extract_information(resume_array, resume_text, "extracted_sections","user_extract_all_sections")
                
                print(f"Successfully extracted information from {file_name}\n\n")
                return resume_array, file_id, file_name
            else:
                print(f"No text extracted from {file_name}")
                return None
        except Exception as e:
            print(f"An error occurred when processing {file_name} from Drive: {str(e)}")
            return None
    else:
        print(f"Skipping non-PDF file {file_name}")
        return None

# Function to integrate with your existing code for processing resumes from Google Drive
def process_resume_from_drive_with_df(file_name, file_id, download_dir="data/user_resumes_drive"):
    """ Process a resume from Google Drive using the DataFrame approach. Args: file_name: Name of the file in Google Drive, file_id: Google Drive file ID, download_dir: Directory to download the file to
        Returns:tuple: (candidate_id, file_id, file_name) if successful, None otherwise"""
    if file_name.lower().endswith(".pdf"):
        print(f"Processing PDF file {file_name}")
        
        # Download file from Google Drive
        print(f"Downloading file: {file_name} (ID: {file_id})")
        download_file(file_id, file_name, download_dir=download_dir)
        resume_path = os.path.join(download_dir, file_name)
        
        try:
            # Create a ResumeProcessor instance and process the resume
            processor = ResumeProcessor()
            candidate_id = processor.process_resume(resume_path)
            
            if candidate_id:
                print(f"Successfully extracted candidate ID: {candidate_id}\n")
                
                # Save the processed data to CSV files
                processor.save_to_csv("data/processed_resumes")
                
                return candidate_id, file_id, file_name
            else:
                print(f"Failed to process resume {file_name}")
                return None
        except Exception as e:
            print(f"An error occurred when processing {file_name} from Drive: {str(e)}")
            import traceback
            print(traceback.format_exc())
            return None
    else:
        print(f"Skipping non-PDF file {file_name}")
        return None

def analyze_resume(resume_array, file_name):
    """Use an LLM to analyze the resume and procide feedbqck
    Args:
    """
    try:
        feedback_result = general_analyzer(resume_array["extracted_sections"])

        if feedback_result:
        #    resume_array["general_feedback"] = feedback_result
        #    print("Added general feedback to resume data.\n")
        
            # Save with original filename
            save_data(resume_array, file_name)

        return feedback_result

    except Exception as e:
            print(f"An error occurred when generating feedback for {file_name} from Drive: {str(e)}")
            return None

def analyze_resume_with_df(candidate_id, file_name):
    """Analyze a resume using the processed dataframes. Args:candidate_id (str): The ID of the candidate whose resume is being analyzed, file_name (str): The original filename for saving results
        Returns: dict: The feedback results or error information."""
    try:
        # Load the processed dataframes
        candidates_df = pd.read_csv("data/processed_resumes/candidates.csv")
        skills_df = pd.read_csv("data/processed_resumes/skills.csv")
        experience_df = pd.read_csv("data/processed_resumes/experience.csv")
        education_df = pd.read_csv("data/processed_resumes/education.csv")
        languages_df = pd.read_csv("data/processed_resumes/languages.csv")
        
        # Filter for this candidate
        candidate_data = candidates_df[candidates_df['candidate_id'] == candidate_id]
        
        # Check if candidate exists
        if candidate_data.empty:
            return {"error": f"Candidate with ID {candidate_id} not found"}
        
        # Get candidate's information
        candidate_skills = skills_df[skills_df['candidate_id'] == candidate_id]
        candidate_experience = experience_df[experience_df['candidate_id'] == candidate_id]
        candidate_education = education_df[education_df['candidate_id'] == candidate_id]
        candidate_languages = languages_df[languages_df['candidate_id'] == candidate_id]
        
        # Get candidate's name
        first_name = candidate_data['first_name'].iloc[0]
        
        # Generate feedback based on the dataframes
        feedback_result = general_analyzer_df(
            first_name=first_name,
            candidate_data=candidate_data,
            skills=candidate_skills,
            experience=candidate_experience,
            education=candidate_education,
            languages=candidate_languages
        )
        
        if feedback_result:
            # Save the feedback
            save_feedback_to_csv(candidate_id, feedback_result, file_name)
            
        return feedback_result
        
    except Exception as e:
        print(f"Error analyzing resume: {e}")
        return {"error": str(e)}

def save_feedback_to_csv(candidate_id, feedback_result, file_name):
    """Save feedback to a CSV file with flattened structure - no nested JSON. Args: candidate_id (str): The ID of the candidate, feedback_result (dict): The feedback to save, file_name (str): The original file name (for reference)"""
    try:
        # Create a feedback dataframe if it doesn't exist
        try:
            feedback_df = pd.read_csv("data/processed_resumes/feedback.csv")
        except FileNotFoundError:
            # Create a dataframe with all the flattened columns we need
            columns = [
                'candidate_id',
                'file_name',
                'timestamp',
                'summary_feedback',
                'summary_example',
                'hard_skills_feedback',
                'hard_skills_example',
                'soft_skills_feedback',
                'soft_skills_example',
                'work_experience_feedback',
                'work_experience_example',
                'education_feedback',
                'education_example',
                'languages_feedback',
                'languages_example'
            ]
            feedback_df = pd.DataFrame(columns=columns)
        
        # Prepare new row with flattened structure
        new_row = {
            'candidate_id': candidate_id,
            'file_name': file_name,
            'timestamp': datetime.now().isoformat()
        }
        
        # Extract and flatten the nested feedback structure
        if 'general_feedback' in feedback_result:
            sections = feedback_result['general_feedback'].get('sections', {})

            # Add summary section feedback and example if available
            if 'summary' in sections:
                new_row['summary_feedback'] = sections['summary'].get('feedback', '')
                new_row['summary_example'] = sections['summary'].get('example', '')
            
            # Add split skills sections (hard and soft) if available
            if 'skills' in sections:
                skills_section = sections['skills']
                
                # Check if skills are already split in the response
                if 'hard_skills' in skills_section:
                    new_row['hard_skills_feedback'] = skills_section['hard_skills'].get('feedback', '')
                    new_row['hard_skills_example'] = skills_section['hard_skills'].get('example', '')
                    new_row['soft_skills_feedback'] = skills_section['soft_skills'].get('feedback', '')
                    new_row['soft_skills_example'] = skills_section['soft_skills'].get('example', '')
                else:
                    # If not split, use the general skills feedback for both (not ideal but prevents data loss)
                    new_row['hard_skills_feedback'] = skills_section.get('feedback', '')
                    new_row['hard_skills_example'] = skills_section.get('example', '')
                    new_row['soft_skills_feedback'] = skills_section.get('feedback', '')
                    new_row['soft_skills_example'] = skills_section.get('example', '')
            
            # Add other sections' feedback and example
            for section_name, section_data in sections.items():
                if section_name not in ['summary', 'skills']:
                    new_row[f'{section_name}_feedback'] = section_data.get('feedback', '')
                    new_row[f'{section_name}_example'] = section_data.get('example', '')
        
        # Add row to dataframe
        feedback_df = pd.concat([feedback_df, pd.DataFrame([new_row])], ignore_index=True)
        
        # Save dataframe
        feedback_df.to_csv("data/processed_resumes/feedback.csv", index=False)
        
        print(f"Saved flattened feedback for candidate {candidate_id}")
        
    except Exception as e:
        print(f"Error saving feedback: {e}")

def email_body_creation(resume_array, resume_feedback):
    try:
        # Check if questions is valid
        if not resume_feedback or "error" in resume_feedback:
            print("Invalid or empty feedback dictionary. Cannot create email body.")
            return None
        
        # Getting user info for email
        user_name = resume_array["extracted_sections"]["user_info"]["first_name"].title()
        user_email = resume_array["extracted_sections"]["user_info"]["email"]
        
        # Create the email body
        opening = f"Hola {user_name},\nRevisé tu CV a detalle y tengo algunas observaciones."
        closing = f"Esas son mis observaciones {user_name}, espero que sean de ayuda."
        
        # Extract the feedback from the dictionary
        feedback_info = resume_feedback.get("general_feedback", {}).get("sections", {})
        
        # Convert the feedback dictionary to a formatted string
        formatted_feedback = ""
        for section, details in feedback_info.items():
            if isinstance(details, dict) and "feedback" in details:
                formatted_feedback += f"\n{section.title()}\n"
                formatted_feedback += f"{details['feedback']}\n"
                
                if "example" in details:
                    if section == "work_experience":
                        formatted_feedback += format_work_experience(details["example"])
                    else:
                        if isinstance(details["example"], list):
                            for example in details["example"]:
                                formatted_feedback += f"- {example}\n"
                        else:
                            formatted_feedback += f"- {details['example']}\n"
                
                formatted_feedback += "\n"
        
        # Check if feedback is empty
        if not formatted_feedback:
            print("No feedback found. Cannot create email body.")
            return None
        
        # Combine opening, feedback, and closing
        formatted_email_body = f"{opening}\n{formatted_feedback}\n{closing}"
        
        # Create the draft
        draft = send_feedback_email_2(user_email, user_name, formatted_email_body)
        if draft:
            print(f"Initial draft created for {user_name}")
        else:
            print("Failed to create initial draft")
            
        return formatted_email_body
        
    except Exception as e:
        print(f"An error occurred when creating the email body: {str(e)}")
        print(f"Raw response: {resume_feedback}")
        print(f"Traceback: {traceback.format_exc()}")
        return None

def email_body_creation_with_df(candidate_id):
    """ Create email body using candidate data from dataframes and feedback results. Args: candidate_id (str): The ID of the candidate, Returns: str: Formatted email body or None if an error occurs"""
    try:
        # Get the candidate feedback using the new function
        feedback_result = get_candidate_feedback(candidate_id)
        
        # Check if feedback exists
        if not feedback_result:
            print(f"No feedback found for candidate {candidate_id}. Cannot create email body.")
            return None
        
        # Load the candidates dataframe
        try:
            candidates_df = pd.read_csv("data/processed_resumes/candidates.csv")
        except FileNotFoundError:
            print("Candidates dataframe not found")
            return None
            
        # Get candidate data
        candidate_data = candidates_df[candidates_df['candidate_id'] == candidate_id]
        if candidate_data.empty:
            print(f"Candidate with ID {candidate_id} not found")
            return None
            
        # Getting user info for email
        user_name = candidate_data['first_name'].iloc[0].title()
        user_email = candidate_data['email'].iloc[0]
        
        # Create the email body
        opening = f"Hola {user_name},\nRevisé tu CV a detalle y tengo algunas observaciones."
        closing = f"Esas son mis observaciones {user_name}, espero que sean de ayuda."
        
        # Process the feedback - assuming the structure is similar but from our flattened feedback
        formatted_feedback = ""
        
        # Check if the feedback contains the expected structure
        if 'feedback_json' in feedback_result:
            import json
            # If feedback is stored as a JSON string, parse it
            try:
                feedback_info = json.loads(feedback_result['feedback_json'])
                sections = feedback_info.get("general_feedback", {}).get("sections", {})
                
                for section, details in sections.items():
                    if isinstance(details, dict) and "feedback" in details:
                        formatted_feedback += f"\n{section.title()}\n"
                        formatted_feedback += f"{details['feedback']}\n"
                        
                        if "example" in details:
                            if section == "work_experience":
                                formatted_feedback += format_work_experience(details["example"])
                            else:
                                if isinstance(details["example"], list):
                                    for example in details["example"]:
                                        formatted_feedback += f"- {example}\n"
                                else:
                                    formatted_feedback += f"- {details['example']}\n"
                        formatted_feedback += "\n"
            except json.JSONDecodeError:
                print("Error decoding feedback JSON")
                return None
        else:
            # Alternative approach if feedback structure is different
            # Add logic to extract relevant feedback from the flattened structure
            sections = ['summary', 'hard_skills', 'soft_skills', 'work_experience', 'education']
            for section in sections:
                section_key = f"{section}_feedback"
                if section_key in feedback_result and feedback_result[section_key]:
                    formatted_feedback += f"\n{section.title()}\n"
                    formatted_feedback += f"{feedback_result[section_key]}\n\n"
                    formatted_feedback += f"Ejemplo:\n"
                    
                # Handle examples if they exist in this format
                example_key = f"{section}_example"
                if example_key in feedback_result and feedback_result[example_key]:
                    if section == "work_experience":
                        formatted_feedback += format_work_experience(feedback_result[example_key])
                    else:
                        examples = feedback_result[example_key]
                        if isinstance(examples, str):
                            examples = [e.strip() for e in examples.split(',')]
                        if isinstance(examples, list):
                            for example in examples:
                                formatted_feedback += f"- {example}\n"
                        else:
                            formatted_feedback += f"- {examples}\n"
                    formatted_feedback += "\n"
        
        # Check if feedback is empty
        if not formatted_feedback:
            print("No formatted feedback generated. Cannot create email body.")
            return None
            
        # Combine opening, feedback, and closing
        formatted_email_body = f"{opening}\n{formatted_feedback}\n{closing}"
        
        # Create the draft email
        draft, draft_id, draft_message_id, draft_message_thread_id, draft_message_label_id = send_feedback_email_2(user_email, user_name, formatted_email_body)
        if draft:
            print(f"Initial draft created for {user_name}")
            # Log the email sending in a CSV file
            log_email_sent(candidate_id, user_email, formatted_email_body, draft_id, draft_message_id, draft_message_thread_id, draft_message_label_id)
        else:
            print("Failed to create initial draft")
            
        return formatted_email_body
        
    except Exception as e:
        print(f"An error occurred when creating the email body: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return None

def format_work_experience(examples):
    """Format work experience examples for the email
    
    Args:
        examples (list or dict): Work experience examples
        
    Returns:
        str: Formatted work experience examples
    """
    formatted_text = ""
    
    if isinstance(examples, list):
        for example in examples:
            if isinstance(example, dict):
                job_title = example.get("job_title", "")
                company = example.get("company", "")
                formatted_text += f"- {job_title} at {company}\n"
            else:
                formatted_text += f"- {example}\n"
    elif isinstance(examples, dict):
        job_title = examples.get("job_title", "")
        company = examples.get("company", "")
        formatted_text += f"- {job_title} at {company}\n"
    else:
        formatted_text += f"- {examples}\n"
        
    return formatted_text

def log_email_sent(candidate_id, email, email_body, draft_id, draft_message_id, draft_message_thread_id, draft_message_label_id):
    """Log email sending in a CSV file
    
    Args:
        candidate_id (str): The candidate ID
        email (str): The email address
        email_body (str): The email body content
    """
    try:
        # Create or load email logs dataframe
        try:
            email_logs_df = pd.read_csv("data/logs/email_logs.csv")
        except FileNotFoundError:
            email_logs_df = pd.DataFrame(columns=[
                'candidate_id', 'email', 'timestamp', 'draft_created', 'email_body', 'draft_id', 'draft_message_id', 'draft_message_thread_id', 'draft_message_label_id'
            ])
        
        # Add new log entry
        new_row = {
            'candidate_id': candidate_id,
            'email': email,
            'timestamp': pd.Timestamp.now().isoformat(),
            'draft_created': True,
            'email_body':email_body,
            'draft_id':draft_id,
            'draft_message_id':draft_message_id,
            'draft_message_thread_id':draft_message_thread_id,
            'draft_message_label_id':draft_message_label_id
        }
        
        # Add row to dataframe
        email_logs_df = pd.concat([email_logs_df, pd.DataFrame([new_row])], ignore_index=True)
        
        # Save dataframe
        email_logs_df.to_csv("data/logs/email_logs.csv", index=False)
        
        print(f"Logged email sent to {email}")
        
    except Exception as e:
        print(f"Error logging email sent: {e}")

def delay(index,total_files):
    # Add delay before processing next file (if there is a next file)
        if index < total_files - 1:  # Only wait if there are more files to process
            print(f"\nWaiting 10 seconds before processing next file to avoid rate limits...")
            time.sleep(10)

def email_body_creation_asking_questions(resume_array, questions):
    """Helper function to create a readable email body.
    Args: resume_array (dict): The whole dictionary containing the resume's data.
        questions (dict): The asked questions structured in a dictionary.
    Returns:
        tuple: A tuple containing the formatted email body, user's first name, and user's email."""
    try:
         # Check if questions is valid
        if not questions or "error" in questions:
            print("Invalid or empty questions dictionary. Cannot create email body.")
            return None, None, None
        
        # Extract user infomation
        user_first_name = resume_array["extracted_sections"]["user_info"]["first_name"].title()
        user_email = resume_array["extracted_sections"]["user_info"]["email"]

        # Create the email body
        opening = f"Hola {user_first_name},\nRevisé tu CV y tengo algunas preguntas para obtener información complementaria y generar una versión mejorada de tu CV. Por favor incluye toda la información que tengas, entre más información de valor, mejor. Dividí mis preguntas por sección y son las siguientes:"
        closing = f"Esas fueron mis preguntas {user_first_name}, se que son varias pero son muy importantes para generar una versión que resalte tus habilidades y así, resulte atractiva para los reclutadores. Quedamos atentos de tus respuestas\nIván Anaya y Marco García"

        # Extract the complementary info (nested dictionary)
        complementary_info = questions.get("asking_complementary_info", {})

        # Convert the questions dictionary to a formatted string
        formatted_questions = ""
        for section, details in complementary_info.items():
            if isinstance(details, dict) and "questions" in details:
                formatted_questions += f"{section.title()}\n"
                for i, question in enumerate(details["questions"], 1):
                    formatted_questions += f"{i}. {question}\n"
                formatted_questions += "\n"  # Add space between sections

        # Combine opening, questions, and closing
        formatted_email_body = f"{opening}\n\n{formatted_questions}\n{closing}"

        return formatted_email_body, user_first_name, user_email
    
    except Exception as e:
        print(f"An error ocurred when creating the email body from the list 'questions': {e}")
        return None
    