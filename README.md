
Sublime-TM1 is a Sublime Text 3 add-in that assists TM1 / Planning Analytics developers a set of tools to assist in the development process.


Features
=======================

Sublime-TM1 has the following features

- Edit TM1 Turbo Integrator and Rules within Sublime Text - [Video](https://imgur.com/IztAeu1)
- Get/Push changes from/to TM1 directly
- Execute processes, view process log - [Video](https://imgur.com/3PiOlIc)
- View running server processes, cancel operation - [Video](https://imgur.com/1ZsUqZe)
- Syntax highlighting for Rule and Turbo Integrator files
- Built-in snippets for Rule and TI functions
- Custom, dynamic snippets for common TM1 turbo integrator tasks - [Video](https://imgur.com/RIx82Px)


Requirements
=======================

- Sublime Text
- TM1       (10.2.2 FP 5 or higher)

Usage
=======================

Setup:
 - Sublime-TM1 can be installed via Package Control [Here](https://packagecontrol.io/installation)
 - Instructions on how to use Package Control [here](https://packagecontrol.io/docs/usage)
 - Install the 'TM1 Planning Analytics Developer Tools' package from Package Control
 - On the TM1 server, the REST API must be enabled, instructions [Here](https://www.ibm.com/support/knowledgecenter/en/SSD29G_2.0.0/com.ibm.swg.ba.cognos.tm1_inst.2.0.0.doc/t_ug_cxr_odata_config.html)

Configuration:
 - Create a folder on your computer to store the TM1 objects
 - Open a new sublime window, and drag the newly created folder into the Sublime Text window. You should see the folder as the only entry in the sidebar.
 - Go to Project -> Save Project As and save the project to location on your PC
 - Open the command palette (CMD/CTRL + SHIFT + P) and enter: TM1: Config - Update TM1 Project Settings
 - Fill in the settings as prompted to connect to the server
 - Open the command palette and enter TM1: Get - Pull Objects From Server to pull objects from the server


Documentation
=======================

Coming soon


Issues
=======================

If you find issues, sign up in Github and open an Issue in this repository


Contribution
=======================

Contributions welcome!

Credit
=======================

Sublime-TM1 makes use of:

 - [TM1py](https://github.com/cubewise-code/TM1py)
 - [prettytable](https://pypi.python.org/pypi/PrettyTable)
