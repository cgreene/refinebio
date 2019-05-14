import re
import urllib

from abc import ABC
from django.utils import timezone
from typing import List, Dict

from data_refinery_common.job_lookup import ProcessorPipeline, Downloaders
from data_refinery_common.logging import get_and_configure_logger
from data_refinery_common.models import (
    OriginalFile,
    SurveyJobKeyValue,
)
from data_refinery_foreman.surveyor import utils
from data_refinery_foreman.surveyor.external_source import ExternalSourceSurveyor

logger = get_and_configure_logger(__name__)

DIVISION_URL_TEMPLATE = ("https://rest.ensembl.org/info/genomes/division/{division}"
                         "?content-type=application/json")
TRANSCRIPTOME_URL_TEMPLATE = ("ftp://ftp.{url_root}/fasta/{species_sub_dir}/dna/"
                              "{filename_species}.{assembly}.dna.{schema_type}.fa.gz")
GTF_URL_TEMPLATE = ("ftp://ftp.{url_root}/gtf/{species_sub_dir}/"
                    "{filename_species}.{assembly}.{assembly_version}.gtf.gz")

# Ensembl will periodically release updated versions of the assemblies.
RELEASE_URL = "https://rest.ensembl.org/info/software?content-type=application/json"

class EnsemblUrlBuilder(ABC):
    """Generates URLs for different divisions of Ensembl.

    Each division of Ensembl has different conventions for its
    URLs. The logic contained in the init method of this base class is
    appropriate for most, but not all of the divisions. However, the
    logic contained in the build_* methods of this class is
    appropriate for all divisions.
    """

    def __init__(self, species: Dict):
        """Species is a Dict containing parsed JSON from the Division API."""
        self.url_root = "ensembl.org/pub/release-{assembly_version}"
        self.assembly = species["assembly_name"]
        self.assembly_version = utils.requests_retry_session().get(
            RELEASE_URL).json()["release"]
        self.species_sub_dir = species["name"]
        self.filename_species = species["name"].capitalize()
        self.taxonomy_id = species["taxonomy_id"]
        self.scientific_name = self.filename_species.replace("_", " ")

    def build_transcriptome_url(self) -> str:
        url_root = self.url_root.format(assembly_version=self.assembly_version)
        url = TRANSCRIPTOME_URL_TEMPLATE.format(url_root=url_root,
                                                species_sub_dir=self.species_sub_dir,
                                                filename_species=self.filename_species,
                                                assembly=self.assembly,
                                                schema_type="primary_assembly")

        # If the primary_assembly is not available use toplevel instead.
        try:
            # Ancient unresolved bug. WTF python: https://bugs.python.org/issue27973
            urllib.request.urlcleanup()
            file_handle = urllib.request.urlopen(url)
            file_handle.close()
            urllib.request.urlcleanup()
        except:
            url = url.replace("primary_assembly", "toplevel")

        return url

    def build_gtf_url(self) -> str:
        url_root = self.url_root.format(assembly_version=self.assembly_version)
        return GTF_URL_TEMPLATE.format(url_root=url_root,
                                       species_sub_dir=self.species_sub_dir,
                                       filename_species=self.filename_species,
                                       assembly=self.assembly,
                                       assembly_version=self.assembly_version)


class MainEnsemblUrlBuilder(EnsemblUrlBuilder):
    """Special logic specific to the main Ensembl division.

    There is one Ensembl division which is just called Ensembl. This
    is confusing so I refer to it as the main Ensembl division. It
    follows the same general pattern as the rest of them for URLs, but
    just not quite the same base URL structure. Also its REST API
    returns JSON with similar data except with slightly different key
    names.
    """

    def __init__(self, species: Dict):
        self.url_root = "ensembl.org/pub/release-{assembly_version}"
        self.short_division = None
        self.species_sub_dir = species["name"]
        self.filename_species = species["name"].capitalize()
        self.assembly = species["assembly"]
        self.assembly_version = utils.requests_retry_session().get(
            MAIN_RELEASE_URL).json()["release"]
        self.scientific_name = self.filename_species.replace("_", " ")
        self.taxonomy_id = species["taxon_id"]


class EnsemblProtistsUrlBuilder(EnsemblUrlBuilder):
    """Special logic specific to the EnsemblProtists division.

    EnsemblProtists is special because the first letter of the species
    name is always capitalized within the name of the file, instead of
    only when there's not a collection subnested.
    """

    def __init__(self, species: Dict):
        super().__init__(species)
        self.filename_species = species["species"].capitalize()


class EnsemblFungiUrlBuilder(EnsemblProtistsUrlBuilder):
    """The EnsemblFungi URLs work the similarly to Protists division.

    EnsemblFungi is special because there is an assembly_name TIGR
    which needs to be corrected to CADRE for some reason.
    """

    def __init__(self, species: Dict):
        super().__init__(species)
        if self.assembly == "TIGR":
            self.assembly = "CADRE"


def ensembl_url_builder_factory(species: Dict) -> EnsemblUrlBuilder:
    """Returns instance of EnsemblUrlBuilder or one of its subclasses.

    The class of the returned object is based on the species' division.
    """
    return EnsemblUrlBuilder(species)

class TranscriptomeIndexSurveyor(ExternalSourceSurveyor):
    def source_type(self):
        return Downloaders.TRANSCRIPTOME_INDEX.value

    def _clean_metadata(self, species: Dict) -> Dict:
        """Removes fields from metadata which shouldn't be stored.

        Also cast any None values to str so they can be stored in the
        database.
        These fields shouldn't be stored because:
        The taxonomy id is stored as fields on the Organism.
        Aliases and groups are lists we don't need.
        """
        species.pop("taxon_id") if "taxon_id" in species else None
        species.pop("taxonomy_id") if "taxonomy_id" in species else None
        species.pop("aliases") if "aliases" in species else None
        species.pop("groups") if "groups" in species else None

        # Cast to List since we're modifying the size of the dict
        # while iterating over it
        for k, v in list(species.items()):
            if v is None:
                species.pop(k)
            else:
                species[k] = str(v)

        return species

    def _generate_files(self, species: Dict) -> None:
        url_builder = ensembl_url_builder_factory(species)
        fasta_download_url = url_builder.build_transcriptome_url()
        gtf_download_url = url_builder.build_gtf_url()
        
        platform_accession_code = species.pop("division")
        self._clean_metadata(species)

        all_new_files = []

        fasta_filename = url_builder.filename_species + ".fa.gz"
        original_file = OriginalFile()
        original_file.source_filename = fasta_filename
        original_file.source_url = fasta_download_url
        original_file.is_archive = True
        original_file.is_downloaded = False
        original_file.save()
        all_new_files.append(original_file)

        gtf_filename = url_builder.filename_species + ".gtf.gz"
        original_file = OriginalFile()
        original_file.source_filename = gtf_filename
        original_file.source_url = gtf_download_url
        original_file.is_archive = True
        original_file.is_downloaded = False
        original_file.save()
        all_new_files.append(original_file)

        return all_new_files

    def survey(self, source_type=None) -> bool:
        """
        Surveying here is a bit different than discovering an experiment
        and samples.
        """
        if source_type != "TRANSCRIPTOME_INDEX":
            return False

        try:
            species_files = self.discover_species()
        except Exception:
            logger.exception(("Exception caught while discovering species. "
                              "Terminating survey job."),
                             survey_job=self.survey_job.id)
            return False

        try:
            for specie_file_list in species_files:
                self.queue_downloader_job_for_original_files(specie_file_list,
                                                             is_transcriptome=True)
        except Exception:
            logger.exception(("Failed to queue downloader jobs. "
                              "Terminating survey job."),
                             survey_job=self.survey_job.id)
            return False

        return True

    def discover_species(self):
        ensembl_division = (
            SurveyJobKeyValue
            .objects
            .get(survey_job_id=self.survey_job.id,
                 key__exact="ensembl_division")
            .value
        )

        logger.info("Surveying %s division of ensembl.",
                    ensembl_division,
                    survey_job=self.survey_job.id)

        r = utils.requests_retry_session().get(DIVISION_URL_TEMPLATE.format(division=ensembl_division))
        # Yes I'm aware that specieses isn't a word. However I need to
        # distinguish between a singular species and multiple species.
        specieses = r.json()

        try:
            organism_name = SurveyJobKeyValue.objects.get(survey_job_id=self.survey_job.id,
                                                          key__exact="organism_name").value
            organism_name = organism_name.lower().replace(' ', "_")
        except SurveyJobKeyValue.DoesNotExist:
            organism_name = None

        all_new_species = []
        if organism_name:
            for species in specieses:
                if (species['name'] == organism_name):
                    all_new_species.append(self._generate_files(species))
                    break
        else:
            for species in specieses:
                all_new_species.append(self._generate_files(species))

        if len(all_new_species) == 0:
            logger.error("Unable to find any species!",
                         ensembl_division=ensembl_division,
                         organism_name=organism_name)

        return all_new_species
