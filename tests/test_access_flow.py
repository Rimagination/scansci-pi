from scansci_html.access_flow import AccessState, AccessStateMachine
from scansci_html.publisher_recipes import GenericRecipe, NatureRecipe, ScienceRecipe, WileyRecipe


def test_nature_state_machine_identifies_wayf_institution_picker():
    page = FlowPage(
        url="https://wayf.springernature.com/?redirect_uri=https%3A%2F%2Fwww.nature.com%2Farticles%2Fs1",
        html="""
        <main>
          <h1>Access through your institution</h1>
          <p>Access subscription content by using your institution's login system.</p>
          <label>Find your institution:</label>
          <input type="text" />
        </main>
        """,
    )

    evidence = AccessStateMachine(NatureRecipe()).inspect(page)

    assert evidence.state == AccessState.INSTITUTION_PICKER
    assert "springer-nature-wayf" in evidence.markers
    assert evidence.url == page.url


def test_nature_state_machine_identifies_human_login_page():
    page = FlowPage(
        url="https://id.tsinghua.edu.cn/do/off/ui/auth/login/form/example",
        html="<html><body><h1>清华大学用户电子身份服务系统</h1><input type='password'></body></html>",
    )

    evidence = AccessStateMachine(NatureRecipe()).inspect(page)

    assert evidence.state == AccessState.HUMAN_LOGIN
    assert "human-login" in evidence.markers


def test_nature_state_machine_identifies_authorized_fulltext():
    page = FlowPage(
        url="https://www.nature.com/articles/s1",
        html="""
        <article class="c-article">
          <h1>Authorized Article</h1>
          <section><h2>Results</h2><p>The results are visible.</p></section>
          <section><h2>Methods</h2><p>The methods are visible.</p></section>
          <section><h2>References</h2><p>The references are visible.</p></section>
        </article>
        """,
    )

    evidence = AccessStateMachine(NatureRecipe()).inspect(page)

    assert evidence.state == AccessState.FULLTEXT
    assert "article-fulltext" in evidence.markers


def test_science_state_machine_identifies_security_challenge():
    page = FlowPage(
        url="https://www.science.org/doi/10.1126/science.aed5051",
        html="""
        <main>
          <h1>Please wait...</h1>
          <p>Checking if the site connection is secure</p>
          <p>This website is using a security service to protect itself from online attacks.</p>
        </main>
        """,
    )

    evidence = AccessStateMachine(ScienceRecipe()).inspect(page)

    assert evidence.state == AccessState.SECURITY_CHALLENGE
    assert "science-security-challenge" in evidence.markers


def test_science_state_machine_identifies_institutional_access_entry():
    page = FlowPage(
        url="https://www.science.org/doi/10.1126/science.aed5051",
        html="""
        <main>
          <h1>Fast cell wall softening causes Venus flytrap closure</h1>
          <a href="/action/ssostart">Institutional Sign In</a>
          <button>Get Access</button>
        </main>
        """,
    )

    evidence = AccessStateMachine(ScienceRecipe()).inspect(page)

    assert evidence.state == AccessState.ACCESS_ENTRY
    assert "science-access-entry" in evidence.markers


def test_science_state_machine_does_not_treat_sso_transition_url_as_access_entry():
    page = FlowPage(
        url="https://www.science.org/action/ssostart?redirectUri=%2Fdoi%2F10.1126%2Fscience.aed5051",
        html="<html><head><title>Login | Science | AAAS</title></head><body></body></html>",
    )

    evidence = AccessStateMachine(ScienceRecipe()).inspect(page)

    assert evidence.state != AccessState.ACCESS_ENTRY
    assert "science-access-entry" not in evidence.markers


def test_science_state_machine_does_not_treat_aaas_id_page_as_institution_picker():
    page = FlowPage(
        url="https://identity.aaas.org/u/login/identifier?state=abc",
        html="""
        <main>
          <h1>LOG IN</h1>
          <label>AAAS ID (EMAIL ADDRESS)*</label><input type="text" />
          <button>LOGIN</button>
        </main>
        """,
    )

    evidence = AccessStateMachine(ScienceRecipe()).inspect(page)

    assert evidence.state != AccessState.INSTITUTION_PICKER


def test_science_state_machine_rejects_preview_with_structured_abstract_gate():
    page = FlowPage(
        url="https://www.science.org/doi/10.1126/science.aed5051",
        html="""
        <main class="article__body">
          <h1>Fast cell wall softening causes Venus flytrap closure</h1>
          <h2>Editor’s summary</h2>
          <p>A short public editor summary is visible.</p>
          <h2>Structured Abstract</h2>
          <h3>INTRODUCTION</h3><p>Structured abstract introduction.</p>
          <h3>RATIONALE</h3><p>Structured abstract rationale.</p>
          <h3>RESULTS</h3><p>Structured abstract results.</p>
          <h3>CONCLUSION</h3><p>Structured abstract conclusion.</p>
          <h2>Abstract</h2><p>The normal abstract is visible.</p>
          <h2>Access the full article</h2>
          <button>Check Access</button>
          <h2>Supplementary Materials</h2>
          <h2>References and Notes</h2>
        </main>
        """,
    )

    evidence = AccessStateMachine(ScienceRecipe()).inspect(page)

    assert evidence.state == AccessState.ACCESS_ENTRY
    assert "science-access-entry" in evidence.markers


def test_science_state_machine_identifies_authorized_fulltext():
    page = FlowPage(
        url="https://www.science.org/doi/10.1126/science.aed5051",
        html="""
        <main class="article__body">
          <h1>Fast cell wall softening causes Venus flytrap closure</h1>
          <section><h2>Abstract</h2><p>The complete abstract is visible.</p></section>
          <section><h2>Introduction</h2><p>The introduction is visible.</p></section>
          <section><h2>Results</h2><p>The results are visible.</p></section>
          <section><h2>References and Notes</h2><p>The references are visible.</p></section>
        </main>
        """,
    )

    evidence = AccessStateMachine(ScienceRecipe()).inspect(page)

    assert evidence.state == AccessState.FULLTEXT
    assert "science-fulltext" in evidence.markers


def test_wiley_state_machine_rejects_abstract_page_with_long_backmatter():
    page = FlowPage(
        url="https://scijournals.onlinelibrary.wiley.com/doi/abs/10.1002/bbb.2202",
        html="""
        <article>
          <h1>Wiley Abstract Page</h1>
          <section><h2>Supporting Information</h2><p>Long supporting information text.</p></section>
          <section><h2>References</h2>
            <p>Reference text mentions materials, immobilization, and other scientific terms.</p>
          </section>
          <section><h2>Citing Literature</h2><p>More long citation text.</p></section>
        </article>
        """,
    )

    evidence = AccessStateMachine(WileyRecipe()).inspect(page)

    assert evidence.state == AccessState.SUBSCRIPTION_PREVIEW
    assert "wiley-abstract-page" in evidence.markers


def test_wiley_state_machine_rejects_abstract_only_article_landing_page():
    page = FlowPage(
        url="https://scijournals.onlinelibrary.wiley.com/doi/10.1002/bbb.2202",
        html="""
        <article>
          <h1>Wiley Abstract Landing Page</h1>
          <section><h2>Abstract</h2>
            <p>A long abstract is visible, but no main body sections are present.</p>
          </section>
          <section><h2>Supporting Information</h2><p>Supporting information text.</p></section>
          <section><h2>References</h2><p>Reference text makes this page long.</p></section>
        </article>
        """,
    )

    evidence = AccessStateMachine(WileyRecipe()).inspect(page)

    assert evidence.state != AccessState.FULLTEXT
    assert "wiley-fulltext" not in evidence.markers


def test_wiley_state_machine_identifies_institutional_access_entry():
    page = FlowPage(
        url="https://onlinelibrary.wiley.com/doi/full/10.1111/gcb.70943",
        html="""
        <article>
          <h1>Cross-Continental Differences in Climate</h1>
          <a>Read the full text</a>
          <a>PDF</a>
          <section><h2>Abstract</h2><p>The public abstract is visible.</p></section>
          <div>
            <p>Get access to the full version of this article.</p>
            <h2>Institutional Login</h2>
            <button>Loading institution options... (or click to choose manually)</button>
          </div>
          <h2>Purchase Instant Access</h2>
        </article>
        """,
    )

    evidence = AccessStateMachine(WileyRecipe()).inspect(page)

    assert evidence.state == AccessState.ACCESS_ENTRY
    assert "wiley-access-entry" in evidence.markers


def test_wiley_state_machine_does_not_treat_search_results_as_human_login():
    page = FlowPage(
        url="https://onlinelibrary.wiley.com/action/doSearch?AllField=Tsinghua%20University",
        html="""
        <main>
          <h1>Articles & Chapters: Tsinghua University</h1>
          <a>Log in</a>
          <form action="/action/doSearch"><input type="search" name="AllField" /></form>
          <article>
            <h2>Industrial Ecology Education at Tsinghua University</h2>
            <p>Search result, not an institution login page.</p>
          </article>
        </main>
        """,
    )

    evidence = AccessStateMachine(WileyRecipe()).inspect(page)

    assert evidence.state != AccessState.HUMAN_LOGIN
    assert "human-login" not in evidence.markers


def test_wiley_state_machine_identifies_authorized_fulltext():
    body = " ".join(["The authorized Wiley article body is visible and readable."] * 20)
    page = FlowPage(
        url="https://nph.onlinelibrary.wiley.com/doi/10.1111/nph.16655",
        html=f"""
        <article>
          <h1>Gemma cup and gemma development</h1>
          <section><h2>I. Introduction</h2><p>{body}</p></section>
          <section><h2>II. Development</h2><p>{body}</p></section>
          <section><h2>V. Conclusion</h2><p>{body}</p></section>
          <section><h2>References</h2><p>The references are visible.</p></section>
        </article>
        """,
    )

    evidence = AccessStateMachine(WileyRecipe()).inspect(page)

    assert evidence.state == AccessState.FULLTEXT
    assert "wiley-fulltext" in evidence.markers


def test_wiley_state_machine_ignores_prebody_sidebar_headings():
    body = " ".join(["The authorized Wiley article body is visible and readable."] * 20)
    page = FlowPage(
        url="https://nph.onlinelibrary.wiley.com/doi/10.1111/nph.16655",
        html=f"""
        <article>
          <h1>Gemma cup and gemma development</h1>
          <h2>Figures</h2>
          <h2>References</h2>
          <h2>Related</h2>
          <h2>Information</h2>
          <section><h2>Summary</h2><p>{body}</p></section>
          <section><h2>I. Introduction</h2><p>{body}</p></section>
          <section><h2>V. Conclusion</h2><p>{body}</p></section>
          <section><h2>References</h2><p>The real references follow the body.</p></section>
        </article>
        """,
    )

    evidence = AccessStateMachine(WileyRecipe()).inspect(page)

    assert evidence.state == AccessState.FULLTEXT
    assert "wiley-fulltext" in evidence.markers


def test_science_recipe_prioritizes_visible_check_access_before_sso_anchor():
    selectors = ScienceRecipe().access_entry_selectors()

    assert selectors.index("a:has-text('Check Access')") < selectors.index("a[href*='/action/ssostart']")


def test_generic_recipe_allows_plain_text_institution_input_without_picker_context():
    recipe = GenericRecipe()
    rule = next(rule for rule in recipe.institution_input_rules() if rule.selector == "input[type='text']")
    page = FlowPage(
        url="https://publisher.example/access",
        html="<html><body><input type='text'></body></html>",
    )

    assert recipe.should_try_institution_input(rule, page) is True


def test_wiley_recipe_blocks_picker_only_inputs_on_article_before_picker_context():
    recipe = WileyRecipe()
    rule = next(rule for rule in recipe.institution_input_rules() if rule.selector == "input[type='search']")
    page = FlowPage(
        url="https://onlinelibrary.wiley.com/doi/full/10.1111/gcb.70943",
        html="""
        <html>
          <header><form action="/action/doSearch"><input type="search" name="AllField"></form></header>
          <article><h1>Wiley Article</h1></article>
        </html>
        """,
    )

    assert recipe.should_try_institution_input(rule, page) is False


def test_wiley_recipe_allows_picker_only_inputs_after_institutional_login_context():
    recipe = WileyRecipe()
    rule = next(rule for rule in recipe.institution_input_rules() if rule.selector == "input[type='search']")
    page = FlowPage(
        url="https://onlinelibrary.wiley.com/doi/full/10.1111/gcb.70943",
        html="""
        <html>
          <body>
            <h2>Institutional Login</h2>
            <button>Loading institution options... (or click to choose manually)</button>
            <input type="search">
          </body>
        </html>
        """,
    )

    assert recipe.should_try_institution_input(rule, page) is True


class FlowPage:
    def __init__(self, *, url: str, html: str):
        self.url = url
        self._html = html

    def content(self):
        return self._html
