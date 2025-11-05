## Workflow outline
- Visit each sam-url url from the input.csv file scrape the following metadata from the page:
    - Title
    - Description
    - Published Date
    - Response Date
    - Set Aside
    - NAICS Code
    - PSC Code
    - Place of Performance
    - Contact Information
    - Department / Agency
    - Sub-tier
    - Office
    - Save the metadata to a new file called sam-metadata.csv
- Also download all the attachments from each sam-url page and save them to a new folder called sam-attachments. We will then run the SAMgov_Document_Summarization_Prompt.md prompt on each attachment to generate a summary of the document.
- Once we have the metadata and summaries for each attachment, we will run the SAMgov_Opportunity_Summarization_Prompt.md prompt to generate a summary of the opportunity.
- We will then save the full summary and short summary to a new file called sam-summary.csv

### Notes
- Each opportuntiy may have zero or more attachements. If there are no attachments, then you should not run the SAMgov_Document_Summarization_Prompt.md prompt.
- Each opportunity may have zero or more document summaries. If there are no document summaries so the opportunity summary should be based on the metadata only if there are zero summaries
- After all the data is collected I want want to create a new viewer app so I can compare the new long and short summaries agains the other summary data in the input.csv file. These new summaries will be titles govbeacon-long-summary and govbeacon-short-summary.
- We will also need a seperate viewer app so I can evaluate the document summaries

## LLM Details
- Use Google gemini API for all prompts
- Use model = "gemini-flash-lite-latest"
- Sample api code in ai_studio_code.py
- You may need to slightly modify the prompts so that you can input the input metadata and document summaries into the prompts.
- API Documentation: https://ai.google.dev/gemini-api/docs / https://ai.google.dev/api
- Use a .env file to store the API key and other sensitive information.
- I may want to test running the data again against differnt LLM models so we should allow for that option and save the results with a timestamped filename.

## Sam.gov scraping
- If you need a sam.gov login, I can provide you with a login and password or login on my chrome browser so you can use that brower and info to scrape the data and download the attachments.

