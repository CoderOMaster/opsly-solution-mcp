import dspy
from dspy_files.helper import gather_repository_info
from dspy_files.repo_analyser import RepositoryAnalyzer
import os
from dotenv import load_dotenv
load_dotenv()
def generate_llms_txt_for_dspy(repo_url="https://github.com/sktime/sktime"):
    """
    Generate an llms.txt summary for a GitHub repository.
    
    Args:
        repo_url (str): The URL of the GitHub repository to analyze.
        
    Returns:
        The analysis result containing the llms.txt content.
    """
    # Configure DSPy
    lm = dspy.LM("gemini/gemini-2.5-flash", api_key=os.getenv("GEMINI_API_KEY"))
    dspy.configure(lm=lm)

    # Initialize our analyzer
    analyzer = RepositoryAnalyzer()

    # Gather repository information
    file_tree, readme_content, package_files = gather_repository_info(repo_url)

    # Generate llms.txt
    result = analyzer(
        repo_url=repo_url,
        file_tree=file_tree,
        readme_content=readme_content,
        package_files=package_files
    )

    return result

# Run the generation
if __name__ == "__main__":
    result = generate_llms_txt_for_dspy()

    # Save the generated llms.txt
    with open("llms.txt", "w") as f:
        f.write(result.llms_txt_content)

    print("Generated llms.txt file!")
    print("\nPreview:")
    print(result.llms_txt_content[:500] + "...")