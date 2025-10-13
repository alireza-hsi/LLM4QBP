import os
import sys
from pathlib import Path


# Add the MAO directory to Python path if needed
mao_path = Path("MAO-custom-versions/Version-1")  # adjust this path to where your MAO folder is
sys.path.append(str(mao_path))

# Import required modules
from camel.typing import ModelType
from run import main

# Define your task and project name
task = """ Module 1: Early Assessment
This module identifies best practices for the early assessment of suspected TIA or minor
(nondisabling) stroke. Patients typically present at the ED, but the same practices should be followed
at an outpatient clinic or when patients are directly admitted to acute care. The recommendations
emphasize assessing the patient to inform clinical decision-making and determine the most
appropriate pathway.
Module 1 Recommended Practices 
1.1 Initial evaluation
1.1.1 Rapid initial evaluation should be conducted for airway,
breathing, and circulation
1.2 Initial examinations
1.2.1 All patients should undergo a neurological examination to
determine focal neurological deficits and assess stroke severity on a
standardized stroke scale (NIHSS or CNS for stroke)
1.2.2 All patients should undergo brain imaging (CT or MRI)
immediately
1.2.3 Brain imaging should be interpreted immediately by a health care
provider with expertise in reading CT and/or MRI
1.2.4 All patients should undergo ECG to detect atrial fibrillation and
other acute arrhythmias
1.2.5 A chest x-ray should not delay assessment for thrombolysis 
1.2.6 All patients should have the following blood work:
• CBC
• electrolytes
• creatinine
• glucose
• INR
• partial thromboplastin time
• troponin test (if clinically indicated)
1.3 Assessment and early management of dysphagia
1.3.1 All patients with stroke should be made NPO initially and have
their swallowing ability screened using a simple, valid, reliable, bedside
testing protocol as part of their initial assessment and before initiating
oral medication, fluid, or food
1.3.2 All patients with stroke who are not alert within the first 24 hours
should be monitored closely, and swallowing ability should be
screened when clinically appropriate
1.3.3 Patients with stroke presenting with features indicating dysphagia
or pulmonary aspiration should receive a full clinical assessment of
their swallowing ability by a speech-language pathologist or
appropriately trained specialist who would advise on swallowing ability
and the required consistency of diet and fluids
1.4 Cross-continuum prevention assessment and therapies
1.4.1 All patients, whether admitted to hospital or discharged from the
ED, should be given appropriate cross-continuum secondary
prevention assessments and therapies (Modules 5 and 10)
1.5 Triage tool for patients with TIA
1.5.1 A standardized triage tool should be used to determine the
appropriate location for the care of patients with TIA
1.6 Initial examinations for TIA or minor (nondisabling) stroke
1.6.1 Patients with a TIA or minor (nondisabling) stroke presenting
within 48 hours of symptom onset or with fluctuating motor or speech
symptoms should undergo immediate vascular imaging of the neck
arteries (carotid ultrasound, CTA, or MRA) unless the patient is clearly
not a candidate for carotid artery revascularization
1.6.2 All other patients (presenting beyond 48 hours) with a TIA or
ischemic stroke should undergo vascular imaging of the brain and
neck arteries as soon as possible
1.7 Recommendations are not applicable to TIA or minor (nondisabling) stroke
Abbreviations: AHA/ASA, American Heart Association/American Stroke Association; Australia, Australian Clinical Guidelines for Stroke
Management; CBC, complete blood count; CSBPR, Canadian Best Practices Recommendations; CNS, Canadian Neurological Scale; CT,
computed tomography; CTA, computed tomography angiography; ECG, electrocardiogram; ED, emergency department; INR, international
normalized ratio; MRA, magnetic resonance angiography; MRI, magnetic resonance imaging; NHS/NICE, National Collaborating Centre for
Chronic Conditions; NIHSS, National Institute of Health Stroke Scale; NPO, nil per os (nothing by mouth); SIGN, Scottish Intercollegiate
Guidelines Network; TIA, transient ischemic attack.

The following implementation considerations were noted by members of the expert advisory panel.

Module 1 Implementation Considerations
General considerations
• Where feasible, EMS should divert patients to regional or district stroke centres if there is suspicion of stroke/TIA
• The process for EMS prenotification of the receiving hospital about a stroke/TIA patient arrival should be better
established to ensure acute stroke teams receive timely and detailed information
• Collaboration between local EMS and institutions that provide stroke services should occur in all stroke networks across
the province to support quality improvement and facilitate access to stroke care
• Ongoing education should be provided to EMS crews about the recognition of stroke/TIA symptoms and regional
medical redirect protocols
• Standardized stroke/TIA assessment and treatment protocols/tools should be developed and used in all Ontario hospital
EDs
• Upon receiving EMS prenotification, the receiving hospital’s acute stroke team should be contacted and called to the ED
(for appropriate patients)
• Sufficient human resources capacity should be ensured so that patients can be diagnosed and treated in a timely
manner
• To facilitate early assessment, hospital-level CTAS I or CTAS II access to diagnostic imaging should be established for
suspected stroke/TIA patients to facilitate early assessment
• A referral process for rapid-assessment TIA and minor stroke units/TIA clinics and provincial stroke-prevention clinics
should be established in all hospitals for patients who are not admitted to hospital
• Efforts to raise public awareness about the symptoms of stroke/TIA and when to contact 911 should continue to be
enhanced and funded
Abbreviations: CTAS, Canadian Triage and Acuity Scale; ED, emergency department; EMS, emergency medical services; TIA, transient
ischemic attack."""

project_name = "MAO_QBP_1_Cleaned_v1"
model = ModelType.GPT_4o

# Run the program
if __name__ == "__main__":
    main(task=task, name=project_name, model=model)