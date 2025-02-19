#!/usr/bin/env python
# noqa: E501


"""
Create CMS 2015 HI ppref collision dataset records.
"""

import click
import csv
import json
import os
import re
import subprocess
import sys
import urllib.parse
import zlib


from create_eos_file_indexes import (
    XROOTD_URI_BASE,
    get_dataset_index_file_base,
    get_dataset_location,
)

recid_freerange_start = 24600
recid_validated_runs_full_validation = 14212
recid_validated_runs_muons_only = 14213
recid_hlt_trigger_configuration = 23900
global_tag = "75X_dataRun2_v13"
cmssw_release = "CMSSW_7_5_8_patch3"
collision_energy = "5.02TeV"
collision_type = "pp"
year_published = "2023"

FWYZARD = {}

SELECTION_DESCRIPTIONS = {}

LINK_INFO = {}
try:
    exec(open("./outputs/reco_config_files_link_info.py", "r").read())
except FileNotFoundError:
    pass

DOI_INFO = {}

RUNNUMBER_CACHE = {}

CONTAINERIMAGES_CACHE = {}

RECOCMSSW_CACHE = {}

RECOGLOBALTAG_CACHE = {}


def get_from_deep_json(data, akey):
    "Traverse DATA and return first value matching AKEY."
    if type(data) is dict:
        if akey in data.keys():
            return data[akey]
        else:
            for val in data.values():
                if type(val) is dict:
                    aval = get_from_deep_json(val, akey)
                    if aval:
                        return aval
                if type(val) is list:
                    for elem in val:
                        aval = get_from_deep_json(elem, akey)
                        if aval:
                            return aval
    if type(data) is list:
        for elem in data:
            aval = get_from_deep_json(elem, akey)
            if aval:
                return aval
    return None


def get_das_store_json(dataset):
    "Return DAS JSON from the DAS JSON Store for the given dataset."
    filepath = "./inputs/das-json-store/" + dataset.replace("/", "@") + ".json"
    with open(filepath, "r") as filestream:
        return json.load(filestream)


def get_number_events(dataset):
    """Return number of events for the dataset."""
    number_events = get_from_deep_json(get_das_store_json(dataset), "nevents")
    if number_events:
        return number_events
    return 0


def get_number_files(dataset):
    """Return number of files for the dataset."""
    number_files = get_from_deep_json(get_das_store_json(dataset), "nfiles")
    if number_files:
        return number_files
    return 0


def get_size(dataset):
    """Return size of the dataset."""
    size = get_from_deep_json(get_das_store_json(dataset), "size")
    if size:
        return size
    return 0


def get_file_size(afile):
    "Return file size of a file."
    return os.path.getsize(afile)


def get_file_checksum(afile):
    """Return the ADLER32 checksum of a file."""
    return hex(zlib.adler32(open(afile, "rb").read(), 1) & 0xFFFFFFFF)[2:].zfill(8)


def populate_fwyzard():
    """Populate FWYZARD dictionary (dataset -> trigger list)."""
    if os.path.exists("./inputs/hlt-2015-hi-ppref-datasets.txt"):
        for line in open("./inputs/hlt-2015-hi-ppref-datasets.txt", "r").readlines():
            line = line.strip()
            dataset, trigger = line.split(",")
            if dataset in FWYZARD.keys():
                FWYZARD[dataset].append(trigger)
            else:
                FWYZARD[dataset] = [
                    trigger,
                ]


def populate_doiinfo():
    """Populate DOI_INFO dictionary (dataset -> doi)."""
    for line in open("./inputs/doi-col.txt", "r").readlines():
        dataset, doi = line.split()
        DOI_INFO[dataset] = doi


def populate_runnumber_cache():
    """Populate RUNNUMBER cache (dataset -> run_numbers)"""
    dataset = ""
    values = []
    for line in open("../cms-YYYY-run-numbers/inputs/allruns.txt", "r").readlines():
        line = line.strip()
        if line.startswith("/"):
            # finish information about the dataset
            if dataset in RUNNUMBER_CACHE.keys():
                print(f"[ERROR] {dataset} existing several times in the input file.")
            else:
                if len(values):
                    values.sort()
                    RUNNUMBER_CACHE[dataset] = values
            # start reading new dataset
            dataset = line
            values = []
        else:
            values.append(str(line))


def populate_containerimages_cache():
    """Populate CONTAINERIMAGES cache (dataset -> system_details.container_images)"""
    with open("../cms-release-info/cms_release_container_images_info.json") as f:
        content = json.loads(f.read())
        for key in content.keys():
            CONTAINERIMAGES_CACHE[key] = content[key]


def populate_recocmssw_cache():
    """Populate CMSSWRECO cache (reco_file_name -> cmssw)"""
    for line in open("./inputs/reco-config-files-cmssw.csv", "r").readlines():
        line = line.strip()
        reco, cmssw = line.split(" ")
        reco = reco.replace(".py", "")
        RECOCMSSW_CACHE[reco] = cmssw


def populate_recoglobaltag_cache():
    """Populate CMSSWGLOBALTAG cache (reco_file_name -> global tag)"""
    for line in open("./inputs/reco-config-files-globaltag.csv", "r").readlines():
        line = line.strip()
        reco, global_tag = line.split(" ")
        reco = reco.replace(".py", "")
        RECOGLOBALTAG_CACHE[reco] = global_tag


def populate_selection_descriptions():
    """Populate SELECTION_DESCRIPTIONS dictionary (dataset -> selection description)."""
    for input_file in [
        "./inputs/CMSDatasetDescription_Run2015E.csv",
    ]:
        if os.path.exists(input_file):
            with open(input_file, "r") as csvfile:
                for line_values in csv.reader(csvfile, delimiter=":"):
                    dataset, description = line_values
                    SELECTION_DESCRIPTIONS[dataset] = description


def create_selection_information(dataset, dataset_full_name):
    """Create box with selection information."""
    out = ""
    # description:
    description = SELECTION_DESCRIPTIONS.get(dataset_full_name, "")
    if description:
        out += f"<p>{description}</p>"
    # data taking / HLT:
    out += "<p><strong>Data taking / HLT</strong>"
    out += f'<br/>The collision data were assigned to different RAW datasets using the following <a href="/record/{recid_hlt_trigger_configuration}">HLT configuration</a>.</p>'
    # data processing / RECO:
    process = "RECO"
    for reco_link in LINK_INFO.keys():
        if f"_{dataset}_" not in reco_link:
            continue
        generator_text = "Configuration file for " + process + " step " + reco_link
        release = RECOCMSSW_CACHE[reco_link]
        global_tag = RECOGLOBALTAG_CACHE[reco_link]
        out += "<p><strong>Data processing / RECO</strong>"
        out += "<br/>This primary AOD dataset was processed from the RAW dataset by the following step (the run number in the configuration file name indicates the first run it was applied to): "
        out += "<br/>Step: %s" % process
        out += "<br/>Release: %s" % release
        out += "<br/>Global tag: %s" % global_tag
        out += '\n        <br/><a href="/record/%s">%s</a>' % (
            LINK_INFO[reco_link],
            generator_text,
        )
        out += "\n        </p>"
    # HLT trigger paths:
    out += "<p><strong>HLT trigger paths</strong>"
    out += '<br/>The possible <a href="/docs/cms-guide-trigger-system#hlt-trigger-path-definitions">HLT trigger paths</a> in this dataset are:'
    trigger_paths = get_trigger_paths_for_dataset(dataset)
    for trigger_path in trigger_paths:
        if trigger_path.endswith("_v"):
            trigger_path = trigger_path[:-2]
        out += '<br/><a href="/search?q=%s&type=Supplementaries&year=2015">%s</a>' % (
            trigger_path,
            trigger_path,
        )
    out += "</p>"
    return out


def get_trigger_paths_for_dataset(dataset):
    """Return list of trigger paths for given dataset."""
    return FWYZARD.get(dataset, [])


def get_dataset_index_files(dataset_full_name):
    """Return list of dataset file information {path,size} for the given dataset."""
    files = []
    dataset_index_file_base = get_dataset_index_file_base(dataset_full_name)
    output = subprocess.getoutput(
        "ls ./inputs/eos-file-indexes/ | grep " + dataset_index_file_base
    )
    for line in output.split("\n"):
        afile = line.strip()
        if afile.endswith(".txt") or afile.endswith(".json"):
            # take only TXT files
            afile_uri = (
                XROOTD_URI_BASE
                + get_dataset_location(dataset_full_name)
                + "/file-indexes/"
                + afile
            )
            afile_size = get_file_size("./inputs/eos-file-indexes/" + afile)
            afile_checksum = get_file_checksum("./inputs/eos-file-indexes/" + afile)
            files.append((afile_uri, afile_size, afile_checksum))
    return files


def get_doi(dataset_full_name):
    "Return DOI for the given dataset."
    return DOI_INFO[dataset_full_name]


def create_record(recid, dataset_full_name):
    """Create record for the given dataset."""

    rec = {}

    m = re.match(r"^/(.*)\/(.*?)-(.*?)/(.*)$", dataset_full_name)
    if not m:
        print(f"[ERROR] Cannot parse dataset {dataset}.")
        sys.exit()
    dataset_short = str(m.groups(1)[0])
    dataset_runperiod = str(m.groups(1)[1])
    dataset_version = str(m.groups(1)[2])
    dataset_format = str(m.groups(1)[3])

    dataset_runperiod_year = dataset_runperiod[3:7]
    dataset_runperiod_runx = dataset_runperiod.replace(dataset_runperiod_year, "")

    rec["abstract"] = {}
    rec["abstract"]["description"] = (
        "<p>"
        + dataset_short
        + f" primary dataset in {dataset_format} format from {dataset_runperiod_runx} of {dataset_runperiod_year}. Run period from run number 261445 to 262328.<p>"
        + "<p>These proton-proton data were taken at the same centre-of-mass energy and have a similar trigger menu to proton-Pb collision data from 2013.</p>"
        + f"<p>The list of validated runs, which must be applied to all analyses, either with the full validation or for an analysis requiring only muons, can be found in</p>"
    )
    rec["abstract"]["links"] = [
        {
            "description": "Validated runs, full validation",
            "recid": str(recid_validated_runs_full_validation),
        },
        {
            "description": "Validated runs, muons only",
            "recid": str(recid_validated_runs_muons_only),
        },
    ]
    rec["accelerator"] = "CERN-LHC"

    rec["collaboration"] = {}
    rec["collaboration"]["name"] = "CMS collaboration"
    rec["collaboration"]["recid"] = "451"

    rec["collections"] = [
        "CMS-Primary-Datasets",
    ]

    rec["collision_information"] = {}
    rec["collision_information"]["energy"] = collision_energy
    rec["collision_information"]["type"] = collision_type

    rec["date_created"] = [
        dataset_runperiod_year,
    ]
    rec["date_published"] = year_published
    rec["date_reprocessed"] = dataset_runperiod_year

    rec["distribution"] = {}
    rec["distribution"]["formats"] = ["aod", "root"]
    rec["distribution"]["number_events"] = get_number_events(dataset_full_name)
    rec["distribution"]["number_files"] = get_number_files(dataset_full_name)
    rec["distribution"]["size"] = get_size(dataset_full_name)

    rec["doi"] = get_doi(dataset_full_name)

    rec["experiment"] = "CMS"

    rec["files"] = []
    rec_files = get_dataset_index_files(dataset_full_name)
    for index_type in [".json", ".txt"]:
        index_files = [f for f in rec_files if f[0].endswith(index_type)]
        for file_number, (file_uri, file_size, file_checksum) in enumerate(index_files):
            rec["files"].append(
                {
                    "checksum": "adler32:" + file_checksum,
                    "description": dataset_short
                    + f" {dataset_format} file index ("
                    + str(file_number + 1)
                    + " of "
                    + str(len(index_files))
                    + ") for access to data",
                    "size": file_size,
                    "type": "index" + index_type,
                    "uri": file_uri,
                }
            )

    rec["keywords"] = ["heavy-ion physics"]

    rec["license"] = {}
    rec["license"]["attribution"] = "CC0"

    rec["methodology"] = {}
    rec["methodology"]["description"] = create_selection_information(
        dataset_short, dataset_full_name
    )

    rec["publisher"] = "CERN Open Data Portal"

    rec["recid"] = str(recid)

    if dataset_full_name in RUNNUMBER_CACHE.keys():
        rec["run_numbers"] = RUNNUMBER_CACHE[dataset_full_name]

    rec["run_period"] = [
        dataset_runperiod,
    ]

    rec["system_details"] = {}
    rec["system_details"]["global_tag"] = global_tag
    rec["system_details"]["release"] = cmssw_release
    if cmssw_release in CONTAINERIMAGES_CACHE.keys():
        rec["system_details"]["container_images"] = CONTAINERIMAGES_CACHE[cmssw_release]

    rec["title"] = dataset_full_name

    rec["title_additional"] = (
        dataset_short
        + f" primary dataset in {dataset_format} format from "
        + dataset_runperiod_runx
        + " of "
        + dataset_runperiod_year
        + " ("
        + dataset_full_name
        + ")"
    )

    rec["type"] = {}
    rec["type"]["primary"] = "Dataset"
    rec["type"]["secondary"] = [
        "Collision",
    ]

    rec["usage"] = {}
    rec["usage"][
        "description"
    ] = "You can access these data through the CMS Open Data container or the CMS Virtual Machine. See the instructions for setting up one of the two alternative environments and getting started in"
    rec["usage"]["links"] = [
        {
            "description": "Running CMS analysis code using Docker",
            "url": "/docs/cms-guide-docker",
        },
        {
            "description": "How to install the CMS Virtual Machine",
            "url": f"/docs/cms-virtual-machine-{dataset_runperiod_year}",
        },
        {
            "description": "Getting Started with CMS 2013 and 2015 Heavy-Ion Open Data",
            "url": "/docs/cms-getting-started-hi-2013-2015",
        },
    ]

    rec["validation"] = {}
    rec["validation"][
        "description"
    ] = "During data taking all the runs recorded by CMS are certified as good for physics analysis if all subdetectors, trigger, lumi and physics objects (tracking, electron, muon, photon, jet and MET) show the expected performance. Certification is based first on the offline shifters evaluation and later on the feedback provided by detector and Physics Object Group experts. Based on the above information, which is stored in a specific database called Run Registry, the Data Quality Monitoring group verifies the consistency of the certification and prepares a json file of certified runs to be used for physics analysis. For each reprocessing of the raw data, the above mentioned steps are repeated. For more information see:"
    rec["validation"]["links"] = [
        {
            "description": "The Data Quality Monitoring Software for the CMS experiment at the LHC: past, present and future",
            "url": "https://www.epj-conferences.org/articles/epjconf/pdf/2019/19/epjconf_chep2018_02003.pdf",
        },
    ]

    return rec


def create_records(dataset_full_names):
    """Create records."""
    records = []
    recid = recid_freerange_start
    for dataset_full_name in dataset_full_names:
        records.append(create_record(recid, dataset_full_name))
        recid += 1
    return records


def print_records(records):
    """Print records."""
    print(
        json.dumps(
            records,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ": "),
        )
    )


@click.command()
def main():
    "Do the job."

    populate_fwyzard()
    populate_doiinfo()
    populate_runnumber_cache()
    populate_containerimages_cache()
    populate_recocmssw_cache()
    populate_recoglobaltag_cache()
    populate_selection_descriptions()

    with open("./inputs/cms-2015-collision-datasets-hi-ppref.txt", "r") as f:
        dataset_full_names = []
        for line in f.readlines():
            dataset_full_names.append(line.strip())
        records = create_records(dataset_full_names)
        print_records(records)


if __name__ == "__main__":
    main()
