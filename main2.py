#main2.py
import os
import json
from core.information_extractor import extract_information, get_resume_text_from_pdf
from core.general_feedback import general_analyzer
from core.handle_resume_from_email import send_feedback_email,  search_emails, get_message, get_label_id, questions_email_draft
from core.handle_resume_from_drive import get_folder_id, number_files_in_drive, process_resume_from_drive, analyze_resume, email_body_creation, delay, email_body_creation_asking_questions, analyze_resume_with_df, process_resume_from_drive_with_df, email_body_creation_with_df
from core.asking_questions import complementary_questions
from data.data_handler import load_data, save_data
from tenacity import retry, stop_after_attempt, wait_exponential

from temporal.temporal import ResumeProcessor, VersionedResumeProcessor

resume_array = load_data()

def email_processing(label_name):
    
    # Get the label ID for "cvagent"
    label_id = get_label_id(label_name) 

    if not label_id:
        print(f"Error: label '{label_name}' not found.")

    message_ids = search_emails(label_ids=[label_id])

    if not message_ids:
        print("No matching emails found")
    
    for msg_id in message_ids:
        email_message = get_message(msg_id)

        if email_message:
            #Extract Information (Sender, Subject, etc.)
            sender_email = email_message['From']
            subject = email_message['Subject']
            
            print(f"Processing email from: {sender_email}, Subject: {subject}")
            
            #Download attachments
            attachments = []
            attachments_part = None

            for part in email_message.walk():
                if part.get_content_maintype() == 'multipart':
                    continue
                if part.get('Content-Disposition') is None:
                    continue
                file_name = part.get_filename()
                if bool(file_name):
                    attachments_part = part
                    attachments.append(file_name)

                    # Create an 'user_resumes' directory if it doesn't exist
                    if not os.path.exists('user_resumes'):
                        os.makedirs('user_resumes')

                    file_path = os.path.join('user_resumes', file_name)
                    with open(file_path, 'wb') as f:
                        f.write(part.get_payload(decode=True))
                    print(f"Attachment '{file_name}' saved to '{file_path}'")

            #Check if there's at least one attachment
            if not attachments:
                print("No attachments found in the email.")
                
            #Assume the first attachment is the resume
            resume_path = os.path.join('user_resumes', attachments[0])            

            if not os.path.exists(resume_path):
                print("Error: File not found")
            else:
                resume_text = get_resume_text_from_pdf (resume_path)

                if resume_text:
    
                    resume_array["pdf_path"] = resume_path
                    resume_array["resume_text"] = resume_text

                    #for section_key, prompt_key in extraction_tasks:
                    extract_information(resume_array,resume_text, "extracted_sections", "user_extract_all_sections")
                    save_data(resume_array)
                    print("Thanks for your resume, I will analyze it and provide feedback\n")
                    user_name = resume_array["user info"]["first_name"]
                    user_email = resume_array["user info"]["email"]

                    general_feedback = general_analyzer(resume_array["resume_text"], user_name)
                    send_feedback_email(user_email, user_name, general_feedback)
                    print(f"El borrador fue creado.")

                else:
                    print("Error: Couldn't extract info from PDF")

if __name__ == "__main__":

    while True:
        source = input("Hey there, would you like to retrieve resumes from your email(e) or from Drive(d)?; type (e/d): ")
        if source.lower() not in ['e', 'd']:
            print("Invalid input. Please type 'e' for email or 'd' for Drive.")
            continue
        if source.lower() == "e":
            label = input("Perfect, what is the name of the label under which you have the resumes: ")
            print("Thanks! give a few minutes to process your emails")
            email_processing(label)
            break
        elif source.lower() == "d":
            drive_folder_path = input("Perfect, what is the path of the folder where the resumes are stored: ")
            print("Thanks! give a few minutes to process your resumes")
            drive_folder_id = get_folder_id(drive_folder_path)

            if drive_folder_id:
                print("Processing resumes from Google Drive...")
                files, total_files = number_files_in_drive(drive_folder_id)
                while True:
                    service = input(f"you have {total_files} files in your drive. Do you need a review (r) or craft a new version (v)?")
                    if service.lower() not in ['r', 'v']:
                        print("Invalid input. Please type 'r' for a review or 'v' to craft a new version.")
                        continue
                    if service.lower() == "r":
                        for index, file in enumerate(files):
                            print(f"\nProcessing file {index + 1} of {total_files}: {file['name']}")
                            
                            # Use the new function instead of the old one
                            result = process_resume_from_drive_with_df(file["name"], file["id"])
                            
                            if result is None:
                                print(f"Skipping file {file['name']} (not a PDF or processing error)")
                                continue
                                
                            candidate_id, file_id, file_name = result
                            
                            # Use the new analyze function
                            feedback_result = analyze_resume_with_df(candidate_id, file_name)
                            
                            # Create email body (would need to be updated for the new data structure)
                            email_body = email_body_creation_with_df(candidate_id)
                            
                            delay(index, total_files)
                        break
                    if service.lower() == "v":
                        for index, file in enumerate(files): 
                            print(f"\nProcessing file {index + 1} of {total_files}: {file['name']}")
                            results = process_resume_from_drive(file["name"], file["id"])
                            if results is None:
                                print(f"Skipping file {file['name']} (not a PDF or processing error)")
                                continue
                            resume_array, file_id, file_name = results
                            questions = complementary_questions(resume_array, file_name)
                            email_body, user_name, recipient_email = email_body_creation_asking_questions(resume_array, questions)

                            questions_email_draft(recipient_email, user_name, email_body)
                            
                            delay(index,total_files)
                        break
            else:
                print(f"Error: Google Drive folder not found at path: {drive_folder_path}")
            break