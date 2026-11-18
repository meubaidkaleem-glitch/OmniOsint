"""The universal input classifier (Phase 2 acceptance: every input type is
classified, and ambiguous input returns every candidate instead of a guess)."""

from __future__ import annotations

import hashlib

import pytest

from omniosint.core.errors import ValidationFailed
from omniosint.indicators import (
    ENTITY_LABELS,
    MAX_INPUT_LENGTH,
    MODULES_BY_ID,
    TYPE_INFO,
    EntityType,
    IndicatorType,
    classify,
    classify_file,
)
from omniosint.indicators.types import TYPE_ORDER
from omniosint.providers.catalog import load_catalogue

T = IndicatorType

# One sample per text input type: (input, expected type of the top reading,
# expected normalised value).
TEXT_SAMPLES: list[tuple[str, IndicatorType, str]] = [
    ("Analyst@Example.ORG", T.EMAIL, "analyst@example.org"),
    ("+44 20 7946 0958", T.PHONE, "+442079460958"),
    ("@Example_Handle", T.USERNAME, "example_handle"),
    ("Example.COM.", T.DOMAIN, "example.com"),
    ("https://Example.com:443/login?next=%2F#top", T.URL, "https://example.com/login?next=%2F"),
    ("198.51.100.7", T.IPV4, "198.51.100.7"),
    ("2001:DB8:0:0::7", T.IPV6, "2001:db8::7"),
    ("10.0.0.1-10.0.0.40", T.IP_RANGE, "10.0.0.1-10.0.0.40"),
    ("AS64500", T.ASN, "AS64500"),
    ("Example University", T.ORGANIZATION, "example university"),
    ("Example Trading Ltd", T.BUSINESS_NAME, "example trading ltd"),
    ("44D88612FEA8A8F36DE82E1278ABB02F", T.FILE_HASH, "44d88612fea8a8f36de82e1278abb02f"),
    (
        "SHA1 Fingerprint=DA:39:A3:EE:5E:6B:4B:0D:32:55:BF:EF:95:60:18:90:AF:D8:07:09",
        T.CERTIFICATE_FINGERPRINT,
        "da39a3ee5e6b4b0d3255bfef95601890afd80709",
    ),
    ("https://github.com/example", T.SOCIAL_PROFILE_URL, "https://github.com/example"),
    (
        "https://github.com/Example/Project.git",
        T.REPOSITORY_URL,
        "https://github.com/example/project",
    ),
    ("pkg:pypi/Example_Package@1.0.0", T.PACKAGE, "pkg:pypi/example-package@1.0.0"),
    ("cve-2021-44228", T.CVE, "CVE-2021-44228"),
    ("Trojan:Win32/Example.A", T.MALWARE_INDICATOR, "Trojan:Win32/Example.A"),
    ("51.5007, -0.1246", T.COORDINATES, "51.5007,-0.1246"),
    (
        "Which domains share infrastructure with example.com?",
        T.QUESTION,
        "Which domains share infrastructure with example.com?",
    ),
]

# Network prefixes are CIDR blocks, which are also IP ranges: see the ambiguity tests.
PREFIX_SAMPLE = "198.51.100.0/24"

FILE_SAMPLES: list[tuple[str, bytes, IndicatorType, str]] = [
    ("photo.jpg", b"\xff\xd8\xff\xe0\x00\x10JFIF\x00", T.IMAGE, "JPEG image"),
    ("chart.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", T.IMAGE, "PNG image"),
    ("report.pdf", b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", T.DOCUMENT, "PDF document"),
    (
        "letter.docx",
        b"PK\x03\x04\x14\x00\x06\x00[Content_Types].xml word/document.xml",
        T.DOCUMENT,
        "Word document",
    ),
    ("notes.txt", b"Meeting notes\nNothing to see here.\n", T.DOCUMENT, "Text document"),
    ("tool.exe", b"MZ\x90\x00\x03\x00\x00\x00\x04\x00", T.FILE, "Windows executable"),
    ("blob.bin", bytes(range(256)), T.FILE, "Unrecognised binary data"),
]


@pytest.mark.parametrize(
    ("text", "expected", "value"), TEXT_SAMPLES, ids=[s[1].value for s in TEXT_SAMPLES]
)
def test_every_text_type_is_classified(text: str, expected: IndicatorType, value: str) -> None:
    result = classify(text)
    assert result.status == "recognized", result
    top = result.candidates[0]
    assert top.type is expected
    assert top.value == value
    assert top.reason
    assert top.modules == TYPE_INFO[expected].modules


def test_network_prefix_is_offered() -> None:
    result = classify(PREFIX_SAMPLE)
    prefix = result.find(T.NETWORK_PREFIX)
    assert prefix is not None and prefix.rank == "strong"
    assert prefix.value == PREFIX_SAMPLE


@pytest.mark.parametrize(
    ("name", "head", "expected", "fmt"), FILE_SAMPLES, ids=[s[0] for s in FILE_SAMPLES]
)
def test_file_types_are_detected_from_content(
    name: str, head: bytes, expected: IndicatorType, fmt: str
) -> None:
    digest = hashlib.sha256(head).hexdigest()
    result = classify_file(name, head, size=len(head), sha256=digest)
    top = result.candidates[0]
    assert top.type is expected
    assert top.details["format"] == fmt
    assert top.value == digest
    assert result.mentions[0].type is T.FILE_HASH and result.mentions[0].value == digest


def test_every_input_type_has_a_sample() -> None:
    covered = {sample[1] for sample in TEXT_SAMPLES} | {sample[2] for sample in FILE_SAMPLES}
    covered.add(T.NETWORK_PREFIX)
    assert covered == set(IndicatorType)


def test_registries_are_complete() -> None:
    assert len(IndicatorType) == 24
    assert set(TYPE_INFO) == set(IndicatorType) == set(TYPE_ORDER)
    assert len(EntityType) == 29
    assert set(ENTITY_LABELS) == set(EntityType)
    for info in TYPE_INFO.values():
        assert all(module in MODULES_BY_ID for module in info.modules), info.type


def test_catalogue_modules_are_known() -> None:
    for entry in load_catalogue().providers:
        assert all(module in MODULES_BY_ID for module in entry.modules), entry.id


# --------------------------------------------------------------------------- ambiguity
@pytest.mark.parametrize(
    ("text", "types"),
    [
        (PREFIX_SAMPLE, {T.IP_RANGE, T.NETWORK_PREFIX}),
        ("da39a3ee5e6b4b0d3255bfef95601890afd80709", {T.FILE_HASH, T.CERTIFICATE_FINGERPRINT}),
        (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            {T.FILE_HASH, T.CERTIFICATE_FINGERPRINT},
        ),
        ("Acme Widgets", {T.ORGANIZATION, T.BUSINESS_NAME}),
        ("alice", {T.USERNAME, T.ORGANIZATION, T.BUSINESS_NAME, T.PACKAGE}),
        ("4155551234", {T.PHONE, T.ASN}),
    ],
)
def test_ambiguous_input_lists_every_candidate(text: str, types: set[IndicatorType]) -> None:
    result = classify(text)
    assert result.status == "ambiguous"
    assert result.best is None
    assert {item.type for item in result.candidates} == types
    assert "Choose" in result.message


def test_specific_readings_suppress_generic_ones() -> None:
    for text in ("example.com", "CVE-2021-44228", "AS15169", "8.8.8.8", "github.com/owner/repo"):
        result = classify(text)
        assert result.status == "recognized", text
        assert not {T.USERNAME, T.ORGANIZATION, T.BUSINESS_NAME} & {
            item.type for item in result.candidates
        }, text


def test_specific_url_readings_lead_and_keep_the_plain_url() -> None:
    result = classify("https://github.com/example/project")
    assert [item.type for item in result.candidates] == [T.REPOSITORY_URL, T.URL]
    assert result.candidates[1].rank == "plausible"


def test_unrecognised_input_explains_itself() -> None:
    for text in ("!!!", "12:34:56", "javascript:alert(1)", "C:\\Users\\me\\file.txt"):
        result = classify(text)
        assert result.status == "unrecognized", text
        assert result.candidates == ()
        assert result.hints
    assert "web addresses" in classify("javascript:alert(1)").hints[0]
    assert "omniosint classify --file" in classify("C:\\Users\\me\\file.txt").hints[0]


# --------------------------------------------------------------------------- validation
def test_oversized_input_is_rejected() -> None:
    with pytest.raises(ValidationFailed):
        classify("a" * (MAX_INPUT_LENGTH + 1))


def test_control_characters_are_rejected() -> None:
    with pytest.raises(ValidationFailed):
        classify("example.com\x00")


def test_invisible_and_direction_characters_are_removed_with_a_note() -> None:
    result = classify("exa\u200bmple.com")
    assert result.candidates[0].value == "example.com"
    assert any("Invisible" in note for note in result.candidates[0].notes)
    spoofed = classify("example\u202e.com")
    assert spoofed.candidates[0].value == "example.com"
    assert any("direction" in note for note in spoofed.candidates[0].notes)


def test_empty_input() -> None:
    result = classify("   ")
    assert result.status == "unrecognized" and result.input == ""


# --------------------------------------------------------------------------- normalisation
def test_url_normalisation_removes_credentials_and_fragment() -> None:
    result = classify("HTTPS://user:secret@Example.COM:8443/a%20b?q=1#frag")
    url = result.candidates[0]
    assert url.value == "https://example.com:8443/a%20b?q=1"
    assert "secret" not in result.model_dump_json()
    assert any("password" in note for note in url.notes)
    assert any("fragment" in note for note in url.notes)


def test_credentials_are_removed_from_any_input() -> None:
    result = classify("Who runs ftp://admin:hunter2@files.example.com/x for this company?")
    assert "hunter2" not in result.model_dump_json()
    assert "admin" not in result.input
    assert result.mentions[0].value == "ftp://files.example.com/x"


def test_internationalised_domains_use_the_ascii_form_as_key() -> None:
    result = classify("B\u00fccher.example.de")
    domain = result.candidates[0]
    assert domain.value == "xn--bcher-kva.example.de"
    assert domain.display == "b\u00fccher.example.de"
    assert domain.entity_type is EntityType.SUBDOMAIN
    assert domain.details["registrable_domain"] == "example.de"


@pytest.mark.parametrize(
    ("text", "rank", "fragment"),
    [
        ("printer.local", "weak", "local network"),
        ("co.uk", "weak", "public suffix"),
        ("readme.md", "plausible", "file extension"),
        ("intranet.corp", "weak", "private networks"),
    ],
)
def test_non_public_domains_are_flagged(text: str, rank: str, fragment: str) -> None:
    domain = classify(text).candidates[0]
    assert domain.type is T.DOMAIN and domain.rank == rank
    assert any(fragment in note for note in domain.notes)


@pytest.mark.parametrize(
    ("text", "scope"),
    [
        ("10.1.2.3", "private"),
        ("192.0.2.10", "documentation"),
        ("100.64.0.1", "shared"),
        ("127.0.0.1", "loopback"),
        ("fe80::1", "link_local"),
        ("8.8.8.8", "global"),
        ("::ffff:10.0.0.1", "private"),
    ],
)
def test_address_scope_is_reported(text: str, scope: str) -> None:
    address = classify(text).candidates[0]
    assert address.details["scope"] == scope
    assert address.details["public"] is (scope == "global")
    if scope != "global":
        assert address.notes


def test_cidr_with_host_bits_is_normalised() -> None:
    result = classify("10.0.0.5/24")
    assert result.candidates[0].value == "10.0.0.0/24"
    assert result.find(T.NETWORK_PREFIX).rank == "weak"  # type: ignore[union-attr]


def test_short_range_notation_is_expanded() -> None:
    result = classify("192.168.1.10-20")
    assert result.candidates[0].value == "192.168.1.10-192.168.1.20"
    assert result.candidates[0].details["addresses"] == 11


@pytest.mark.parametrize(("text", "value"), [("AS1.10", "AS65546"), ("asn 13335", "AS13335")])
def test_asn_forms(text: str, value: str) -> None:
    assert classify(text).candidates[0].value == value


def test_private_asn_is_flagged() -> None:
    asn = classify("AS64512").candidates[0]
    assert any("Private AS" in note for note in asn.notes)


def test_phone_without_country_code_needs_one() -> None:
    result = classify("020 7946 0958")
    phone = result.candidates[0]
    assert phone.rank == "weak" and phone.details["needs_country_code"] is True
    with_region = classify("020 7946 0958", default_region="GB").candidates[0]
    assert with_region.value == "+442079460958" and with_region.rank == "plausible"


def test_phone_results_carry_the_subscriber_caveat() -> None:
    phone = classify("+44 20 7946 0958").candidates[0]
    assert any("does not look up subscribers" in note for note in phone.notes)
    assert phone.details["numbering_plan_region"] == "GB"


def test_username_results_carry_the_identity_caveat() -> None:
    username = classify("@example_handle").candidates[0]
    assert any("never proof" in note for note in username.notes)


def test_fediverse_handle() -> None:
    handle = classify("@Alice@Mastodon.Social").candidates[0]
    assert handle.type is T.USERNAME and handle.value == "alice@mastodon.social"


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("npm:lodash@4.17.21", "pkg:npm/lodash@4.17.21"),
        ("@types/node", "pkg:npm/@types/node"),
        ("pkg:npm/%40angular/core@17.0.0", "pkg:npm/@angular/core@17.0.0"),
        ("cargo:serde", "pkg:cargo/serde"),
        ("go:github.com/gin-gonic/gin", "pkg:golang/github.com/gin-gonic/gin"),
        ("maven:org.example:widget:1.2", "pkg:maven/org.example/widget@1.2"),
    ],
)
def test_package_forms(text: str, value: str) -> None:
    package = classify(text).candidates[0]
    assert package.type is T.PACKAGE and package.value == value


def test_repository_ssh_form() -> None:
    repository = classify("git@github.com:Owner/Repo.git").candidates[0]
    assert repository.type is T.REPOSITORY_URL
    assert repository.value == "https://github.com/owner/repo"


@pytest.mark.parametrize(
    "text",
    ["https://twitter.com/home", "https://github.com/settings", "https://www.instagram.com/p/"],
)
def test_platform_pages_are_not_profiles(text: str) -> None:
    assert classify(text).find(T.SOCIAL_PROFILE_URL) is None


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("geo:40.7128,-74.0060", "40.7128,-74.006"),
        ("51\u00b030\u203202\u2033N 0\u00b007\u203229\u2033W", "51.500556,-0.124722"),
        ("51 30 2 N, 0 7 29 W", "51.500556,-0.124722"),
    ],
)
def test_coordinate_forms(text: str, value: str) -> None:
    coordinates = classify(text).candidates[0]
    assert coordinates.type is T.COORDINATES and coordinates.value == value


def test_coordinates_out_of_range_are_not_coordinates() -> None:
    assert classify("91.5, 10.1").find(T.COORDINATES) is None


def test_fuzzy_hashes_and_lookalikes() -> None:
    ssdeep = classify("3:AXGBicFlgVNhBGcL6wCrFQEv:AXGHsNhxLsr2C").candidates[0]
    assert ssdeep.details["algorithm"] == "ssdeep"
    assert classify("12:34:56").status == "unrecognized"


# --------------------------------------------------------------------------- threat input
def test_defanged_indicators_are_restored_and_offered_as_threat_indicators() -> None:
    result = classify("hxxps://evil[.]example[.]com/payload")
    assert result.refanged is True
    url = result.candidates[0]
    assert url.type is T.URL and url.value == "https://evil.example.com/payload"
    threat = result.find(T.MALWARE_INDICATOR)
    assert threat is not None and threat.details["indicator_type"] == "url"
    assert any("defanged" in note for note in url.notes)


def test_defanged_address() -> None:
    result = classify("198[.]51[.]100[.]7")
    assert result.candidates[0].value == "198.51.100.7"
    assert result.find(T.PHONE) is None


def test_malpedia_identifier() -> None:
    result = classify("win.emotet")
    assert result.candidates[0].type is T.MALWARE_INDICATOR


# --------------------------------------------------------------------------- questions
def test_questions_list_the_indicators_they_mention() -> None:
    result = classify(
        "Find infrastructure shared by example.com and 198.51.100.7, then CVE-2021-44228."
    )
    assert result.candidates[0].type is T.QUESTION
    assert result.candidates[0].entity_type is None
    mentions = {(item.type, item.value) for item in result.mentions}
    assert mentions == {
        (T.DOMAIN, "example.com"),
        (T.IPV4, "198.51.100.7"),
        (T.CVE, "CVE-2021-44228"),
    }


def test_names_are_never_read_as_people() -> None:
    result = classify("Jane Example")
    assert {item.type for item in result.candidates} <= {T.ORGANIZATION, T.BUSINESS_NAME}
    assert all(item.entity_type is not EntityType.PERSON_REFERENCE for item in result.candidates)
    assert any("private individuals" in note for note in result.candidates[0].notes)


def test_scripts_are_files_and_never_documents() -> None:
    result = classify_file("run.ps1", b"Write-Host 'hello'\n")
    assert result.candidates[0].type is T.FILE
    assert any("never runs" in note for note in result.candidates[0].notes)


def test_misleading_extension_is_reported() -> None:
    result = classify_file("invoice.pdf", b"MZ\x90\x00\x03\x00")
    top = result.candidates[0]
    assert top.type is T.FILE
    assert any(".pdf" in note and "misleading" in note for note in top.notes)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("192.0.2.10", "Recognised as an IPv4 address."),
        ("example.com", "Recognised as a domain."),
        ("CVE-2024-3094", "Recognised as a CVE identifier."),
        ("someone@example.com", "Recognised as an email address."),
    ],
)
def test_messages_read_naturally(text: str, message: str) -> None:
    assert classify(text).message == message


def test_every_type_label_reads_naturally_in_a_sentence() -> None:
    from omniosint.indicators.wording import with_article

    phrases = {info.label: with_article(info.label) for info in TYPE_INFO.values()}
    assert phrases["Username"] == "a username"
    assert phrases["URL"] == "a URL"
    assert phrases["IPv6 address"] == "an IPv6 address"
    assert phrases["Geographic coordinates"] == "geographic coordinates"
    assert all(" an u" not in f" {phrase}" for phrase in phrases.values())
