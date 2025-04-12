import pandas as pd
import fitz  # PyMuPDF
import uuid
import hashlib
import ast
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from typing import Dict, Tuple, List, Optional
from dataclasses import dataclass
from datetime import datetime
import re
from data.data_handler import load_prompt
from api_integration.gemini_api import GeminiAPI

import os
import json

gemini_api = GeminiAPI()

class RateLimitException(Exception):
    pass

PROMPTS = {}

prompt_files = {
    "user_extract_all_sections": "user_all_sections_extraction_v2.txt"
}

# Load each prompt with error checking
for key, filename in prompt_files.items():
    prompt_content = load_prompt(filename)
    if prompt_content is not None:
        PROMPTS[key] = prompt_content
    else:
        print(f"Warning: Failed to load prompt for {key}")

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type(RateLimitException)
)

def retry_generate_content(prompt):
    try:
        response = gemini_api.generate_content(prompt)
        if not response:
            raise RateLimitException("Empty response from Gemini API")
        return response
    except Exception as e:
        if "429" in str(e) or "Resource has been exhausted" in str(e):
            print("Rate limit hit, waiting before retry...")
            raise RateLimitException(str(e))
        raise

@dataclass
class UserInfo:
    first_name: str
    last_name: str
    email: str
    phone_number: Optional[str] = None
    linkedin_profile: Optional[str] = None
    address: Optional[str] = None
    summary: Optional[str] = None

@dataclass
class Skills:
    soft_skills: Optional[str]
    hard_skills: Optional[str]

@dataclass
class WorkExperience:
    title: str
    company: str
    start_date: str
    description: str
    end_date: Optional[str] = None # optional to hanlde the current positions
    location: Optional[str] = None

@dataclass
class Education:
    title: str
    institution: str
    type: str
    start_date: str
    end_date: Optional[str] = None
    notes: Optional[str] = None

@dataclass
class Language:
    language: str
    level: str
    notes: Optional[str] = None

@dataclass
class ResumeVersion:
    version_id: str
    candidate_id: str
    version_number: int
    pdf_path: str
    revision_date: datetime
    revision_type: str
    reviewer_id: Optional[str]
    previous_version_id: Optional[str]
    changes_summary: Optional[str]
    content_hash: str

class RateLimitException(Exception):
    """Exception raised when API rate limit is exceeded."""
    pass

class ResumeProcessor:
    def __init__(self):
        # Initialize all dataframes with version_id column
        self.candidates_df = pd.DataFrame()
        self.skills_df = pd.DataFrame()
        self.experience_df = pd.DataFrame()
        self.education_df = pd.DataFrame()
        self.languages_df = pd.DataFrame()

    def extract_text(self, pdf_path: str) -> Optional[str]:
        #Extract text from PDF.
        try:
            with fitz.open(pdf_path) as doc:
                text = " ".join(page.get_text() for page in doc)
            return text
        except Exception as e:
            print(f"Error extracting text from PDF {pdf_path}: {e}")
            return None

    def _parse_date_range(self, date_str: str) -> tuple[Optional[str], Optional[str]]:
        #Helper method to parse date ranges from resume, handling multiple formats and edge cases.
        if not date_str:
            return None, None
        
        # Normalize separators and spaces
        date_str = date_str.replace('–', '-').replace(' to ', '-').strip()

        # Handle "Present" or "Current" as end date
        if any(term in date_str.lower() for term in ['present', 'current', 'actual']):
            date_str = re.sub(r'(present|current|actual)', '', date_str, flags=re.IGNORECASE).strip()
            parts = date_str.split('-')
            start_date = parts[0].strip() if parts[0].strip() else None
            return start_date, None
        
        # Split into start and end dates
        parts = re.split(r'[-–]', date_str, maxsplit=1)
        if len(parts) < 2:
            return parts[0].strip(), None
        
        start_date, end_date = parts[0].strip(), parts[1].strip()

        # Handle incomplete end dates (e.g., "2020 - ")
        if not end_date:
            end_date = None

        # Handle localized month names (e.g., Spanish)
        month_translations = {
            'enero': 'January', 'febrero': 'February', 'marzo': 'March',
            'abril': 'April', 'mayo': 'May', 'junio': 'June',
            'julio': 'July', 'agosto': 'August', 'septiembre': 'September',
            'octubre': 'October', 'noviembre': 'November', 'diciembre': 'December'
        }
        for es, en in month_translations.items():
            if start_date:
                start_date = start_date.lower().replace(es, en)
            if end_date:
                end_date = end_date.lower().replace(es, en)

        # Convert to standard format (optional)
        try:
            if start_date:
                start_date = datetime.strptime(start_date, '%b %Y').strftime('%Y-%m')
            if end_date:
                end_date = datetime.strptime(end_date, '%b %Y').strftime('%Y-%m')
        except ValueError:
            # Fallback to raw date if parsing fails
            pass
        
        return start_date, end_date
    
    def _parse_single_date(self, date_str: str) -> Optional[str]:
        """Helper method to parse a single date from resume, handling multiple formats."""
        if not date_str:
            return None
        
        # Clean up the date string
        date_str = date_str.strip()
        
        # Handle "Present" or "Current" as special case
        if any(term in date_str.lower() for term in ['present', 'current', 'actual']):
            return None
        
        # Handle localized month names (e.g., Spanish)
        month_translations = {
            'enero': 'January', 'febrero': 'February', 'marzo': 'March',
            'abril': 'April', 'mayo': 'May', 'junio': 'June',
            'julio': 'July', 'agosto': 'August', 'septiembre': 'September',
            'octubre': 'October', 'noviembre': 'November', 'diciembre': 'December'
        }
        
        for es, en in month_translations.items():
            date_str = date_str.lower().replace(es, en)
        
        # Try to standardize the date format if possible
        try:
            # First try the "Month Year" format
            standardized_date = datetime.strptime(date_str, '%b %Y').strftime('%b %Y')
            return standardized_date
        except ValueError:
            try:
                # Try "Month Year" with full month name
                standardized_date = datetime.strptime(date_str, '%B %Y').strftime('%b %Y')
                return standardized_date
            except ValueError:
                try:
                    # Try "MM/YYYY" format
                    standardized_date = datetime.strptime(date_str, '%m/%Y').strftime('%b %Y')
                    return standardized_date
                except ValueError:
                    try:
                        # Try "YYYY-MM" format
                        standardized_date = datetime.strptime(date_str, '%Y-%m').strftime('%b %Y')
                        return standardized_date
                    except ValueError:
                        # Return the original if we can't parse it
                        return date_str

    def process_resume(self, pdf_path: str) -> str:
        """Main method to process a resume PDF. Returns:str: candidate_id for the processed resume"""
        # Extract text from the PDF
        resume_text = self.extract_text(pdf_path)
        
        if not resume_text:
            print(f"Could not extract text from {pdf_path}")
            return None

        
        # Extract all sections using LLM pero no estoy usando esta variable, podría no guardar esta info en una variable. Dentro de extract_information_with_df actualizo resume_data que es lo que uso en el siguiente paso.
        extracted_sections, resume_data = self.extract_information_with_df(pdf_path, resume_text, "extracted_sections", "user_extract_all_sections")

        if not extracted_sections:
            print(f"Failed to extract sections from {pdf_path}")
            return None

        # Get user info to identify if it is a new user or is already in our data base
        user_info_data = extracted_sections.get('user_info', {}).copy()
        first_name=user_info_data.get('first_name', '')
        last_name=user_info_data.get('last_name', '')
        email=user_info_data.get('email', '')
        phone_number=user_info_data.get('phone_number')

        already_user, id = self.new_user_verification(first_name, last_name, email, phone_number)
        if already_user:
            candidate_id = id
            resume_data["CandidateID"] = candidate_id
        else:
            candidate_id = str(uuid.uuid4())
            resume_data["CandidateID"] = candidate_id
        
        

        # Process the extracted sections into the dataframes
        self.process_llm_output(candidate_id, resume_data, pdf_path, None)
        
        return candidate_id
    
    def extract_information_with_df(self, pdf_path, resume_txt, section_key, prompt_key):
        """
        Extract information from resume text using LLM.
        This is temporarily using your existing extraction function
        """
        try:
            # Ensure prompt_key exists in PROMPTS dictionary
            if prompt_key not in PROMPTS:
                print(f"Error: {prompt_key} not found in PROMPTS dictionary")
                return None

            # Get the prompt template and format it with the resume text
            prompt_template = PROMPTS[prompt_key]
            prompt = prompt_template.format(resume_data=resume_txt)

            # Use retry mechanism for API call
            try:
                response = retry_generate_content(prompt)
            except RateLimitException as e:
                print(f"Failed to generate content after retries: {e}")
                return None
            except Exception as e:
                print(f"Unexpected error during content generation: {e}")
                return None
                
            # Convert response to string and clean it
            response_text = str(response).strip()
            try:
                # Remove any leading/trailing whitespace and newlines
                response_text = response_text.strip()
            
                # If the response is wrapped in markdown code blocks, extract the JSON
                if '```json' in response_text:
                    response_text = response_text.split('```json')[1].split('```')[0].strip()
                elif '```' in response_text:
                    response_text = response_text.split('```')[1].split('```')[0].strip()

                # Parse the JSON
                parsed_response = json.loads(response_text)

                # Create a resume data object
                resume_data = {
                    "file_path": pdf_path,
                    "resume_text": resume_txt
                }
                resume_data[section_key] = parsed_response

                return parsed_response, resume_data
            
            except json.JSONDecodeError as json_err:
                print(f"\nJSON parsing error: {str(json_err)}")
                print("Response text that failed to parse:")
                print(response_text)
                return None
            
        except Exception as e:
            print(f"Error extracting {section_key}: {str(e)}")
            print("Full error:")
            import traceback
            print(traceback.format_exc())
            return None

    def process_llm_output(self, candidate_id, llm_output: Dict, pdf_path: str, version_id: Optional[str] = None):
        """ Process LLM output and update all dataframes automatically."""
        # Use provided version_id or generate a new candidate_id
        timestamp = datetime.now()

        # Add version_id to all records if provided
        base_record = {
            'candidate_id': candidate_id,
            'processed_at': timestamp,
            'version_id': version_id  
        }

        # define base columns 
        base_columns = list(base_record.keys())  # Extract keys from base_record

         # Access the extracted sections
        extracted_sections = llm_output.get('extracted_sections', {})

        # Process user info and summary
        # Adjust key names based on your actual LLM output structure
        user_info_data = extracted_sections.get('user_info', {}).copy() 
        
        # Create UserInfo object, with default values for missing fields
        user_info = UserInfo(
            first_name=user_info_data.get('first_name', ''),
            last_name=user_info_data.get('last_name', ''),
            email=user_info_data.get('email', ''),
            phone_number=user_info_data.get('phone_number'),
            linkedin_profile=user_info_data.get('linkedin_profile'),
            address=user_info_data.get('address'),
            summary=user_info_data.get('summary')
        )
        
        candidate_data = {
            **base_record,
            'first_name': user_info.first_name,
            'last_name': user_info.last_name,
            'email': user_info.email,
            'phone_number': user_info.phone_number,
            'linkedin_profile': user_info.linkedin_profile,
            'address': user_info.address,
            'summary': user_info.summary,
            'pdf_path': pdf_path
        }
        self.candidates_df = pd.concat([
            self.candidates_df,
            pd.DataFrame([candidate_data])
        ], ignore_index=True)

        # Process skills with version_id
        if 'skills' in extracted_sections and extracted_sections['skills']: 
             # Create Skills object
            skills_data = extracted_sections['skills']

            # Ensure skills are stored as actual lists, not string representations
            soft_skills = skills_data.get('soft_skills', [])
            hard_skills = skills_data.get('hard_skills', [])

            # Create Skills object
            skills = Skills(
                soft_skills=soft_skills,
                hard_skills=hard_skills
            )

            skills_record = {
                **base_record,
                'soft_skills': skills.soft_skills,
                'hard_skills': skills.hard_skills
            }

            self.skills_df = pd.concat([
                self.skills_df,
                pd.DataFrame([skills_record])
            ], ignore_index=True)

        # Process relevant work experience with version_id
        if 'relevant_work_experience' in extracted_sections and extracted_sections['relevant_work_experience']:
            experience_records = []
            for exp in extracted_sections['relevant_work_experience']:
                try:
                    # Get date information
                    start_date_str = exp.get('start_date', '')
                    end_date_str = exp.get('end_date', '')

                    # Parse individual dates
                    start_date = self._parse_single_date(start_date_str)
                    end_date = self._parse_single_date(end_date_str)

                    # Get date information
                    #start_date = exp.get('start_date', '')
                    # Parse date range
                    #start_date = self._parse_date_range(start_date)
                    #start_date, end_date = self._parse_date_range(start_date)
                     # Get date information
                    #end_date = exp.get('end_date', '')
                    # Parse date range
                    #start_date, end_date = self._parse_date_range(end_date)
                    #end_date = self._parse_date_range(end_date)
                except Exception as e:
                    print(f"Error parsing date range: {e}")
                    start_date, end_date = None, None  # Fallback to None values

                # Create work experience object   
                work_experience = WorkExperience(
                    title=exp.get('title', ''),
                    company=exp.get('company', ''),
                    start_date=start_date,
                    end_date=end_date,
                    description=exp.get('description', ''),
                    location=exp.get('location')
                )
                # Append record to list
                experience_records.append({
                    **base_record,
                    'title': work_experience.title,
                    'company': work_experience.company,
                    'start_date': work_experience.start_date,
                    'end_date': work_experience.end_date,
                    'description': work_experience.description,
                    'location': work_experience.location
                })
            
            # Concatenate all records at once
            if experience_records:
                self.experience_df = pd.concat([
                    self.experience_df,
                    pd.DataFrame(experience_records)
                ], ignore_index=True)

        # Process education
        if 'education' in extracted_sections and extracted_sections['education']:
            education_records = []

            # Handle education - adapt based on your actual JSON structure
            for edu in extracted_sections['education']:
                # If education is a list of objects rather than nested structure
                if isinstance(edu, dict) and 'title' in edu:
                     # Get date information
                    start_date_str = edu.get('start_date', '')
                    end_date_str = edu.get('end_date', '')

                    # Parse individual dates
                    start_date = self._parse_single_date(start_date_str)
                    end_date = self._parse_single_date(end_date_str)
                    
                    education = Education(
                        title=edu.get('title', ''),
                        institution=edu.get('institution', ''),
                        type=edu.get('type', 'degree'),
                        start_date=start_date,
                        end_date=end_date,
                        notes=edu.get('notes')
                    )
                    
                    education_records.append({
                        **base_record,
                        'title': education.title,
                        'institution': education.institution,
                        'type': education.type,
                        'start_date': education.start_date,
                        'end_date': education.end_date,
                        'notes': education.notes,
                    })
                # Handle nested structure with degrees and certifications
                else:
                    # Handle degrees if present
                    for degree in edu.get('degrees', []):
                        # Get date information
                        start_date_str = degree.get('start_date', '')
                        end_date_str = degree.get('end_date', '')

                        # Parse individual dates
                        start_date = self._parse_single_date(start_date_str)
                        end_date = self._parse_single_date(end_date_str)
                        
                        education = Education(
                            title=degree.get('title', ''),
                            institution=degree.get('institution', ''),
                            type='degree',
                            start_date=start_date,
                            end_date=end_date,
                            notes=degree.get('notes')
                        )
                        
                        education_records.append({
                            **base_record,
                            'title': education.title,
                            'institution': education.institution,
                            'type': education.type,
                            'start_date': education.start_date,
                            'end_date': education.end_date,
                            'notes': education.notes,
                        })
                    
                    # Handle certifications if present
                    for cert in edu.get('certifications', []):
                        # Get date information
                        start_date_str = cert.get('start_date', '')
                        end_date_str = cert.get('end_date', '')

                        # Parse individual dates
                        start_date = self._parse_single_date(start_date_str)
                        end_date = self._parse_single_date(end_date_str)
                        
                        education = Education(
                            title=cert.get('title', ''),
                            institution=cert.get('institution', ''),
                            type='certification',
                            start_date=start_date,
                            end_date=end_date,
                            notes=cert.get('notes')
                        )
                        
                        education_records.append({
                            **base_record,
                            'title': education.title,
                            'institution': education.institution,
                            'type': education.type,
                            'start_date': education.start_date,
                            'end_date': education.end_date,
                            'notes': education.notes,
                        })
            
            if education_records:
                self.education_df = pd.concat([
                    self.education_df,
                    pd.DataFrame(education_records)
                ], ignore_index=True)

        # Process languages with version_id
        if 'languages' in extracted_sections and extracted_sections['languages']:
            language_records = []
            for lang_data in extracted_sections['languages']:
                # Handle different possible structures
                if isinstance(lang_data, dict):
                    language = Language(
                        language=lang_data.get('language', ''),
                        level=lang_data.get('level', ''),
                        notes=lang_data.get('notes')
                    )
                    
                    language_records.append({
                        **base_record,
                        'language': language.language,
                        'level': language.level,
                        'notes': language.notes,
                    })

            if language_records:
                self.languages_df = pd.concat([
                    self.languages_df,
                    pd.DataFrame(language_records)
                ], ignore_index=True)

    def get_dataframes(self) -> Dict[str, pd.DataFrame]:
        #Return all dataframes for analysis or export.

        dataframes = {
            'candidates': self.candidates_df.copy(),
            'skills': self.skills_df.copy(),
            'experience': self.experience_df.copy(),
            'education': self.education_df.copy(),
            'languages': self.languages_df.copy()
        }

        # Process the skills dataframe to handle list serialization properly
        if not dataframes['skills'].empty:
            # Convert list objects to strings for CSV storage
            if 'soft_skills' in dataframes['skills'].columns:
                dataframes['skills']['soft_skills'] = dataframes['skills']['soft_skills'].apply(
                    lambda x: x if isinstance(x, str) else str(x)
                )

            if 'hard_skills' in dataframes['skills'].columns:
                dataframes['skills']['hard_skills'] = dataframes['skills']['hard_skills'].apply(
                    lambda x: x if isinstance(x, str) else str(x)
                )
        return dataframes

    def save_to_csv(self, output_dir: str):
        """Save all dataframes to CSV files with append functionality."""
        os.makedirs(output_dir, exist_ok=True)
        
        for name, df in self.get_dataframes().items():
            if not df.empty:
                file_path = f"{output_dir}/{name}.csv"

                # Check if file exists
                if os.path.exists(file_path):
                    # Read existing data
                    existing_df = pd.read_csv(file_path)

                    # Only for the skills dataframe, convert string lists to actual lists
                    if name == 'skills':
                        if 'soft_skills' in existing_df.columns:
                            existing_df['soft_skills'] = existing_df['soft_skills'].apply(
                                lambda x: ast.literal_eval(x) if isinstance(x, str) and x.strip().startswith('[') else 
                                ([] if pd.isna(x) or x == '' else x)
                            )

                        if 'hard_skills' in existing_df.columns:
                            existing_df['hard_skills'] = existing_df['hard_skills'].apply(
                                lambda x: ast.literal_eval(x) if isinstance(x, str) and x.strip().startswith('[') else 
                                ([] if pd.isna(x) or x == '' else x)
                            )
                    # Append new data
                    combined_df = pd.concat([existing_df, df], ignore_index=True)

                    # Save combined data
                    combined_df.to_csv(file_path, index=False)
                else:
                    # Create new file if it doesn't exist
                    df.to_csv(file_path, index=False)

    def new_user_verification(self, first_name, last_name, email, phone_number):
        file_path = "data/processed_resumes/candidates.csv"
    
        # Check if the file exists
        if not os.path.exists(file_path):
            return False, None


        # File exists, proceed with verification
        candidates_df = pd.read_csv(file_path)

        # Check if any row matches all conditions
        mask = ((candidates_df["first_name"] == first_name) & 
                (candidates_df["last_name"] == last_name) & 
                (candidates_df["email"] == email) & 
                (candidates_df["phone_number"] == phone_number))
        
        if mask.any():  # Check if any row matches all conditions
            matching_row = candidates_df[mask].iloc[0]  # Get the first matching row
            #print(f"Nombre: {first_name} igual a: {matching_row['first_name']} \n"
            #    f"Apellido: {last_name} igual a: {matching_row['last_name']}\n"
            #    f"email: {email} igual a: {matching_row['email']}\n"
            #    f"Telefono: {phone_number} igual a: {matching_row['phone_number']}")
            id = matching_row['candidate_id']
            return True, id
        else:
            return False, None


# Versioning part

class VersionedResumeProcessor(ResumeProcessor):
    def __init__(self, llm_client):
        super().__init__()
        self.versions_df = pd.DataFrame()
        self.llm_client = llm_client  # Store LLM client for processing

    def _calculate_content_hash(self, resume_content: Dict) -> str:
        #Calculate a hash of the resume content to detect actual changes.
        content_str = str(sorted(str(resume_content.items())))
        return hashlib.sha256(content_str.encode()).hexdigest()

    def _get_latest_version(self, candidate_id: str) -> Optional[Dict]:
        #Get the latest version information for a candidate.
        if self.versions_df.empty:
            return None
        
        candidate_versions = self.versions_df[
            self.versions_df['candidate_id'] == candidate_id
        ]
        
        if candidate_versions.empty:
            return None
            
        return candidate_versions.sort_values(
            'version_number', 
            ascending=False
        ).iloc[0].to_dict()

    def process_resume_version(
        self,
        pdf_path: str,
        candidate_id: str,
        revision_type: str,
        reviewer_id: Optional[str] = None,
        changes_summary: Optional[str] = None
    ):
        """Process a new version of a resume with version tracking."""
        # Extract and process resume content
        resume_text = self.extract_text(pdf_path)
        if not resume_text:
            raise ValueError(f"Could not extract text from {pdf_path}")
        
        # Create a resume data object for the LLM
        resume_data = {
            "CandidateID": candidate_id or str(uuid.uuid4()),
            "file_path": pdf_path,
            "resume_text": resume_text
        }
        
        # Get LLM response
        llm_response = self.extract_information_with_df(resume_data, resume_text, "extracted_sections", "user_extract_all_sections")
        
        if not llm_response:
            raise ValueError(f"Failed to extract content from {pdf_path}")
        
        # Use candidate_id from resume_data if not provided
        if not candidate_id:
            candidate_id = resume_data["CandidateID"]
        
        # Calculate content hash
        content_hash = self._calculate_content_hash(llm_response)
        
        # Get latest version info
        latest_version = self._get_latest_version(candidate_id)
        
        # Check if content actually changed
        if latest_version and latest_version['content_hash'] == content_hash:
            print(f"Warning: No significant content changes detected for candidate {candidate_id}")
            return None
        
        # Determine version number
        version_number = (
            latest_version['version_number'] + 1
            if latest_version else 1
        )
        
        # Create version record
        version_id = str(uuid.uuid4())
        version = ResumeVersion(
            version_id=version_id,
            candidate_id=candidate_id,
            version_number=version_number,
            pdf_path=pdf_path,
            revision_date=datetime.now(),
            revision_type=revision_type,
            reviewer_id=reviewer_id,
            previous_version_id=latest_version['version_id'] if latest_version else None,
            changes_summary=changes_summary,
            content_hash=content_hash
        )
        
        # Add version record
        version_data = {
            'version_id': version.version_id,
            'candidate_id': version.candidate_id,
            'version_number': version.version_number,
            'pdf_path': version.pdf_path,
            'revision_date': version.revision_date,
            'revision_type': version.revision_type,
            'reviewer_id': version.reviewer_id,
            'previous_version_id': version.previous_version_id,
            'changes_summary': version.changes_summary,
            'content_hash': version.content_hash
        }
        
        self.versions_df = pd.concat([
            self.versions_df,
            pd.DataFrame([version_data])
        ], ignore_index=True)
        
        # Process the resume content with version tracking
        super().process_llm_output(llm_response, pdf_path, version.version_id)
        return candidate_id
