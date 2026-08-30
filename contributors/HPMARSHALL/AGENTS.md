# AGENTS.md
Guide for LLM agents pulling NISAR data from ASF

## when using
Make sure Plan Mode is being used.
I want to use the Research-Plan-Implement approach.
Please first research how to approach the request, then create a PLAN.md file that outlines the planned approach.
Allow human comments/changes, and require approval before implementing.
Show data size and run a test that downloads only one datafile prior to any larger downloads.

## when writing new code
Prioritize simple, understandable code over efficiency.
Provide lots of comments when creating code.
Make code concise and readable.

## resources
Primary source of info for NISAR data here:
https://nisar-docs.asf.alaska.edu/

## location
For this work we will focus only on the area defined by MCS_domain.kml

# skills
Skills for this work are in nicer-nisar/.agents/skills/HPMARSHALL/