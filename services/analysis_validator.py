
def validate_structure(structure, total_pages):
    units = sorted(
        structure.units,
        key=lambda unit: unit.start_page
    )

    covered_pages = set()
    previous_end = 0

    for unit in units:
        if not (
            1 <= unit.start_page
            <= unit.end_page
            <= total_pages
        ):
            raise ValueError(
                f"잘못된 페이지 범위: {unit.title}"
            )

        if unit.start_page <= previous_end:
            raise ValueError(
                f"학습 단원 페이지 중복: {unit.title}"
            )

        covered_pages.update(
            range(
                unit.start_page,
                unit.end_page + 1
            )
        )

        previous_end = unit.end_page

    excluded_pages = set(structure.excluded_pages)

    invalid_excluded = [
        page
        for page in excluded_pages
        if not 1 <= page <= total_pages
    ]

    if invalid_excluded:
        raise ValueError(
            f"잘못된 제외 페이지: {invalid_excluded}"
        )

    overlapping = covered_pages & excluded_pages

    if overlapping:
        print(
            f"중복 분류된 페이지 발견: {sorted(overlapping)}"
        )

        excluded_pages -= overlapping

        print(
            "중복 페이지를 제외 목록에서 제거했습니다."
        )

    expected_pages = set(
        range(1, total_pages + 1)
    )

    missing_pages = expected_pages - (
        covered_pages | excluded_pages
    )

    if missing_pages:
        raise ValueError(
            f"분류되지 않은 페이지: "
            f"{sorted(missing_pages)}"
        )

    structure.units = units
    structure.excluded_pages = sorted(excluded_pages)

    return structure


def validate_analysis(units, total_pages):
    for unit in units:
        if not (
            1 <= unit.start_page
            <= unit.end_page
            <= total_pages
        ):
            raise ValueError(
                f"잘못된 학습 범위: {unit.title}"
            )

        if not unit.title.strip():
            raise ValueError("단원 제목이 비어 있습니다.")

        if not unit.key_concepts:
            raise ValueError(
                f"핵심 개념이 없습니다: {unit.title}"
            )

        if not unit.summary.strip():
            raise ValueError(
                f"요약이 없습니다: {unit.title}"
            )

    return units
