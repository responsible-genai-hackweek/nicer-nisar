# NICER NISAR!

This is a project repository for the NASA Responsible GenAI Hackweek 2026 https://github.com/responsible-genai-hackweek/responsible-genai-hackweek. This is an exploratory project, the primary goal is for us to learn!

Our plan is to demonstrate how Skills, MCP, or other agentic AI enhancements may or may not improve results for a couple scientific workflow use cases. Specifically, we plan to see how agentic interact with the [NISAR User Guide](https://nisar-docs.asf.alaska.edu) and references therein to instructions to determine a glacier velocity, or to determine snow melt timing or snow depth, for a given area of interest and time range.

## Files and folders in your project repository

A repository to explore (Skills/MCP/other) to demonstrate improved outcomes for a couple scientific workflows by drawing on the latest information on the regularly updated ASF NISAR User Guide + linked references.

* **`contributors/`**
<br> Each team member can create their own folder under contributors, within which they can work on their own scripts, notebooks, and other files. Having a dedicated folder for each person helps to prevent conflicts when merging with the main branch. This is a good place for team members to start off exploring data and methods for the project.
* **`notebooks/`**
<br> Notebooks that are considered delivered results for the project should go in here.
* **`scripts/`**
<br> Code that is shared by the team should go in here (e.g. functions or subroutines). These will be files other than Jupyter Notebooks such as Python scripts (.py).
* `.gitignore`
<br> This file sets the files that will be globally ignored by `git` for the project. (e.g. you may want git to ignore temporary files or large data files, [read more about ignoring files here](https://docs.github.com/en/get-started/getting-started-with-git/ignoring-files))
* `README.md`
<br> Description of the project (see suggested headings below)
* `model-card.md`
<br> Description (following a metadata standard) of any machine learning models used in the project

### Collaborators

List all participants on the project. Here is a good space to share your personal goals for the hackweek and things you can help with.

| Name | Personal goals | Can help with | Role |
| ------------- | ------------- | ------------- | ------------- |
| Scott Henderson (@scottyhq) | I want to better understand the various ways to customize an agentic harness to work efficiently.  | I can help with understanding SAR data and processing | Project Lead |
| Andrew Joros (@ajoros) | ... | ... | Project Co-Lead |
| Joe Kennedy (@jhkennedy) | ... | ... | Team Member  |
| Eric Gagliano (@egagli) | ... | ... | Team Member  |
| Joachim Meyer (@jomey) | ... | ... | Team Member  |
| Wei Ji Leong (@weiji14) | ... | ... | Team Member  |
| Hp Marshall (@hpmarshall) | ... | ... | Team Member  |
| Ibrahim O Alabi (@Ibrahim-Ola) | ... | ... | Team Member  |
| Derek Pickell (@derekpickell) | ... | ... | Team Member  |

### The problem

NISAR is a recently launched NASA-ISRO Synthetic Aperture Radar satellite mission. It has many modes of acquisition and levels of data products that can be confusing for users to navigate. The NISAR User Guide is a living document that is updated regularly, and it contains many references to other documents and resources which may or may not readily consumable by AI agents. There are several problems scientists face with NISAR data, including: Which data product is right for my use-case? How do I isolate the right files for an area of interest and time range? Then if I have a workflow in mind (e.g. determine the velocity of a given glacier), how will AI agents arrive at a result (which data access pattern will they use, which methods will the use and which existing software libraries will they leverage? And ultimately, will agents produce a defensible result that can be reproduced by an expert in the field?

## Data and Methods

### Data

NISAR Data is known to be large and complex, producing 80TB of data daily (https://science.nasa.gov/blogs/nisar/2025/07/30/nasa-isros-nisar-mission-by-the-numbers/)! However, many studies hone in on a small geographic region and date range which requires 10s to 100s of GB of data.

### Existing methods

Traditionally, scientists will 1. Search google or specific websites to hone in on data like https://search.asf.alaska.edu, https://nisar-docs.asf.alaska.edu. Download data, perhaps with https://github.com/earthaccess-dev/earthaccess or https://github.com/asfadmin/Discovery-asf_search, and finally 3. Figure out how to load, run computations to estimate some physical quantity and its uncertainty, and generate figures and tables to summarize the results.

### Proposed methods/tools

We will primarily use Python to work with NISAR data for this project.

1. Write SKILL.md files to make agents more effecient
  * https://agentskills.io/home, https://vercel.com/docs/agent-resources/skills,
1. Write an MCP server - but first try using an existing one https://github.com/nasa/earthdata-mcp!
  * https://github.com/jasongilman/mcp-eval-demo
1. Try making existing documentation more agent-friendly
  * https://llmstxt.org/ and https://github.com/jupyter-book/mystmd/issues/1647
1. Explore a [VirtualizeZarr](https://virtualizarr.readthedocs.io/en/stable/) approach to working with NISAR data.

### Additional resources or background reading


#### Glacier velocity

1. This are neat on-demand pixel tracking workflows that might be a neat to extend to NISAR data and compare results against. Run by ASF https://github.com/ASFHyP3/hyp3-autorift or run via GitHub Actions https://github.com/gbrencher/autorift_actions

#### Snow melt timing and snow depth

TODO


## Project goals and tasks

### Project goals

List the specific project goals or research questions you want to answer. Think about what outcomes or deliverables you'd like to create (e.g. a series of tutorial notebooks demonstrating how to work with a dataset, results of an anaysis to answer a science question, an example of applying a new analysis method, or a new python package).

* Goal 1: Everyone on the team learns something new
* Goal 2: Document fail cases for the status quo of agentic AI applied to NISAR data, and Document wins!
* Goal 3: A set of slides targeted at NASA representatives to explain this effort and possible next steps

### Tasks

What are the individual tasks or steps that need to be taken to achieve each of the project goals identified above? What are the skills that participants will need or will learn and practice to complete each of these tasks? Think about which tasks are dependent on prior tasks, or which tasks can be performed in parallel.

TODO

* Task 1: Gather 2-3 AOIs and time ranges
* Task 2: Each team member creates a subfolder under contributors to document and track their personal work.
* Task 3
* ...

## Project Results

TODO

Use this section to briefly summarize your project results. This could take the form of describing the progress your team made to answering a research question, developing a tool or tutorial, interesting things found in exploring a new dataset, lessons learned for applying a new method, personal accomplishments of each team member, or anything else the team wants to share.

You could include figures or images here, links to notebooks or code elsewhere in the repository (such as in the [notebooks](notebooks/) folder), and information on how others can run your notebooks or code.
