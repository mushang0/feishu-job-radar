from jobpicky.normalizer import infer_city
from jobpicky.locations import canonical_location_id, location_options, match_target_location
from jobpicky.wondercv import parse_wondercv_list


def test_infer_city_extracts_city_names_from_text():
    text = "\u4e0a\u6d77\u5e02 \u6df1\u5733\u5e02 \u6210\u90fd\u5e02 \u5317\u4eac\u5e02"

    assert infer_city(text) == "\u4e0a\u6d77\u5e02;\u6df1\u5733\u5e02;\u6210\u90fd\u5e02;\u5317\u4eac\u5e02"


def test_infer_city_does_not_treat_arbitrary_words_ending_with_city_suffix_as_city():
    text = "\u534f\u52a9\u54c1\u724c\u4e0e\u5e02\u573a\u7814\u7a76 \u56fd\u9645\u5e02\u573a \u4e0a\u6d77\u5e02"

    assert infer_city(text) == "\u4e0a\u6d77\u5e02"


def test_parse_wondercv_list_infers_city_when_no_city_element_exists():
    html = """
    <html><body>
      <a href="/xiaozhao/acme-11409-abc">
        <h2>Acme 2027 campus FPGA engineer \u4e0a\u6d77\u5e02 \u6df1\u5733\u5e02</h2>
        <span class="company">Acme</span>
        <span class="date">2026.07.02</span>
      </a>
    </body></html>
    """

    jobs = parse_wondercv_list(html, "https://www.wondercv.com/xiaozhao/", {})

    assert jobs[0].city == "\u4e0a\u6d77\u5e02;\u6df1\u5733\u5e02"


def test_location_library_has_province_and_prefecture_level_choices():
    sections = location_options()
    guangdong = next(section for section in sections if section["value"] == "province:44")

    assert guangdong["label"] == "广东省"
    assert {city["label"] for city in guangdong["cities"]} >= {"广州市", "深圳市", "珠海市"}
    assert canonical_location_id("深圳") == "city:4403"


def test_location_match_supports_province_city_and_legacy_names():
    assert match_target_location("深圳市", ["province:44"]) == "广东省"
    assert match_target_location("深圳市", ["深圳"]) == "深圳市"
    assert match_target_location(None, ["city:4403"]) is None
    assert canonical_location_id("北京") == "city:11"
    assert match_target_location("北京市", ["province:11"]) == "北京市"
