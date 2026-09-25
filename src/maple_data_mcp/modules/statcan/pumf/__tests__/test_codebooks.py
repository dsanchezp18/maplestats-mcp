"""Codebook parsers, on excerpts of the real files (2026-09-24)."""

from __future__ import annotations

from maple_data_mcp.modules.statcan.pumf import codebooks

LFS_CSV = (
    "Field_Champ,Position_Position,Length_Longueur,Variable_Variable,EnglishLabel_EtiquetteAnglais,"
    "FrenchLabel_EtiquetteFrancais,EnglishUniverse_UniversAnglais,FrenchUniverse_UniversFrancais,"
    "EnglishNote_NoteAnglais,FrenchNote_NoteFrancais\n"
    "1,1,7,rec_num,Order of record in file,Ordre,All respondents,Tous,,\n"
    ",,,1-9999999,,,,,,\n"
    "4,14,1, lfsstat    ,Labour force status,Situation d'activité,All,Tous,,\n"
    ',,,1,"Employed, at work","Personnes occupées, au travail",,,,\n'
    ",,,3,Unemployed,Chômeurs,,,,\n"
)

CENSUS_DCT = """infile dictionary {
    _column(8)       byte                             agegrp   %2f "age"
  _column(321)     double                             weight  %16f "individuals weighting factor"
}"""

CENSUS_DO = """#delimit ;
label define agegrp
1 "0 to 4 years"
2 "5 to 6 years"
;
label values agegrp agegrp ;
"""

CCHS_DCT = """infix dictionary using ??? {
    str    VERDATE  1 - 8
           GEOGPRV  31 - 32
}"""

CCHS_FMT_DO = 'label define GEOGPRV_FMT 10 "NL" 35 "Ontario"\n'
CCHS_VALE_DO = "label values GEOGPRV GEOGPRV_FMT\n"
CCHS_LBE_DO = 'label variable GEOGPRV   "Province of residence"\n'

EICS_VARE = """VARIABLE LABELS
    GENDER         "Gender of respondent"
    WTPM           "Weight"
."""

EICS_VALE = """VALUE LABELS
              /GENDER
                  "1"   "Men+"
                  "2"   "Women+"
              /AF_05
                    1   "You"
."""


def test_lfs_csv_in_both_languages():
    english = codebooks.parse_codebook_csv(LFS_CSV, "en")
    assert english["LFSSTAT"].label == "Labour force status"
    assert (english["LFSSTAT"].position, english["LFSSTAT"].width) == (14, 1)
    assert [v.label for v in english["LFSSTAT"].values] == ["Employed, at work", "Unemployed"]
    assert english["REC_NUM"].values == []  # a range, not a code
    french = codebooks.parse_codebook_csv(LFS_CSV, "fr")
    assert french["LFSSTAT"].values[1].label == "Chômeurs"


def test_stata_dct_and_do_merge():
    found = codebooks.parse_stata_dct(CENSUS_DCT)
    codebooks.merge(found, codebooks.parse_stata_do(CENSUS_DO))
    assert (found["AGEGRP"].label, found["AGEGRP"].position) == ("age", 8)
    assert [v.code for v in found["AGEGRP"].values] == ["1", "2"]
    assert found["WEIGHT"].width == 16


def test_label_sets_attached_from_another_do_file():
    found = codebooks.parse_stata_dct(CCHS_DCT)
    codebooks.merge(
        found, codebooks.parse_stata_do(f"{CCHS_FMT_DO}\n{CCHS_VALE_DO}\n{CCHS_LBE_DO}")
    )
    assert found["GEOGPRV"].label == "Province of residence"
    assert (found["GEOGPRV"].position, found["GEOGPRV"].width) == (31, 2)
    assert [v.label for v in found["GEOGPRV"].values] == ["NL", "Ontario"]
    assert "GEOGPRV_FMT" not in found


def test_spss_labels():
    found = codebooks.parse_spss(EICS_VARE)
    codebooks.merge(found, codebooks.parse_spss(EICS_VALE))
    assert found["GENDER"].label == "Gender of respondent"
    assert [(v.code, v.label) for v in found["GENDER"].values] == [("1", "Men+"), ("2", "Women+")]
    assert found["AF_05"].values[0].label == "You"


SAS = {
    "input": "INPUT\n    @         6     GENDER    1.\n    @        8     REGION6  $  2.\n",
    "labels": 'label\n    GENDER = "Gender of respondent"\n    REGION6 = "Region"\n;',
    "formats": "format\n    GENDER    D00003F.\n    REGION6  $D00012F.\n;",
    "values": 'proc format;\n    VALUE     D00003F\n        1 = "Male +"\n        2 = "Female +"\n        ;\n'
    '    VALUE    $D00012F\n       10 = "Atlantic"\n        ;\n',
}


def test_sas_command_files():
    found = codebooks.parse_sas(SAS)
    assert (found["GENDER"].position, found["GENDER"].width) == (6, 1)
    assert found["GENDER"].label == "Gender of respondent"
    assert [v.label for v in found["GENDER"].values] == ["Male +", "Female +"]
    assert (found["REGION6"].width, found["REGION6"].values[0].code) == (2, "10")
