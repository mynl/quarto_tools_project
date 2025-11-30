"""
Code related to the blog.
"""


# blog conversion tools
# based on blog_tools.py from \s\telos\blog\python

from datetime import datetime
import pandas as pd
from pathlib import Path
import re
import yaml
from itertools import count
from subprocess import Popen, PIPE
from IPython.display import display, Markdown
import logging


logger = logging.getLogger(__name__)

try:
    from pdf2image import convert_from_path
    has_convert_from_path = True
except ModuleNotFoundError:
    # logger.warning('No pdf2image...cannot convert PDF files to png.')
    has_convert_from_path = False


BLOG_BASE = Path('/s/telos/blog/quarto/convexconsiderations/posts')
BLOG_BASE_DEV = Path('/s/telos/blog/quarto/DevConvexConsiderations/posts')
OUTPUT_DIR = Path("/s/telos/blog/quarto/convexconsiderations/docs")


class Post:
    def __init__(self, post_dir):
        """
        Encapsulates one post.

        text = whole text of document
        txt  = text of the post, without the YAML header

        """

        self.post_dir = Path(post_dir)
        self.name = self.post_dir.name
        self.index_file = self._find_index_file()
        if not self.index_file.exists():
            raise ValueError(f'Cannot find index file for {post_dir}')
        self.text = self.index_file.read_text(encoding='utf-8')
        self.stat = self.index_file.stat()
        self.yaml_data, self.txt = self._parse_yaml_front_matter()

    def _find_index_file(self):
        # Assuming the index file ends with '.qmd'
        for file in self.post_dir.glob('index.qmd'):
            return file
        return None

    def _parse_yaml_front_matter(self):
        try:
            parts = self.text.split('---', 2)
            if len(parts) > 2:
                yaml_part = parts[1]
                text_part = parts[2]
                return yaml.safe_load(yaml_part), text_part
            else:
                print(f'parse split has too few parts {parts}')
        except yaml.YAMLError as exc:
            print(f"Error parsing YAML: {exc}")
        except Exception as e:
            print(f"Error reading index file: {e}")
        return {}

    def save(self):
        """
        Save post, reflecting any possible changes.
        """
        out = '\n'.join(
            ['---', yaml.dump(self.yaml).strip(), '---\n', self.txt])
        file = self.post_dir / "index.qmd"
        file.write_text(out, encoding='utf-8')

    @property
    def size(self):
        return self.stat.st_size

    @property
    def file_create_date(self):
        return datetime.fromtimestamp(self.stat.st_ctime)

    @property
    def file_modify_date(self):
        return datetime.fromtimestamp(self.stat.st_mtime)

    @property
    def post_date(self):
        return self.yaml_data.get('date', '')

    @property
    def num_images(self):
        """
        Count the number of images, via links
        """
        markdown_links = re.findall(
            r'(!\[[^]]*\])\(([^)]+)\)', self.text, flags=re.MULTILINE)
        html_links = re.findall(
            '<img (.*)/>', self.text, flags=re.MULTILINE)
        mlinks = len(markdown_links)
        hlinks = len(html_links)
        return mlinks + hlinks

    @property
    def num_tables(self):
        tables = re.findall(r'^(\|:?\-+:?\|)+$',
                            self.text, flags=re.MULTILINE)
        return len(tables)

    @property
    def num_tikz(self):
        tikz = re.findall(r'tikzpicture', self.text)
        return len(tikz)

    @property
    def yaml(self):
        return self.yaml_data

    @property
    def categories(self):
        return self.yaml_data.get('categories', None)

    @property
    def bibliography(self):
        return self.yaml_data.get('bibliography', '')

    @property
    def csl(self):
        return self.yaml_data.get('csl', '')

    def row(self):
        d = str(self.post_dir.relative_to(BLOG_BASE))
        nm = self.post_dir.name[11:].replace('-', ' ')
        link = f'<a href="/posts/{d}">{nm}</a>'.replace('\\', '/')
        return [d,
                nm,
                link,
                ', '.join(self.categories),
                self.size, self.post_date,
                self.file_modify_date, self.num_images, self.num_tables,
                self.num_tikz, self.bibliography]

    def rows_by_category(self):
        d = str(self.post_dir.relative_to(BLOG_BASE))
        nm = self.post_dir.name[11:].replace('-', ' ')
        link = f'<a href="/posts/{d}">{nm}</a>'.replace('\\', '/')
        return [[link, self.post_date, c] for c in self.categories]

    @staticmethod
    def columns():
        return ['directory', 'name', 'link', 'category', 'size', 'posted', 'modified',
                'images', 'tables', 'tikz', 'bibtex']

    def preview(self):
        """
        For Jupyter Lab, preview the post as markdown
        """
        display(Markdown(self.txt))


def post_factory(dev=True):
    if dev:
        p = Path(BLOG_BASE_DEV)
        assert p.exists(), f'Post directory {BLOG_BASE_DEV} does not exist'
    else:
        p = Path(BLOG_BASE)
        assert p.exists(), f'Post directory {BLOG_BASE} does not exist'
    ans = {}
    for f in p.rglob('*'):
        # directory and name starts with a date
        if f.is_dir() and re.match(r'^\d{4}-\d{2}-\d{2}', f.name):
            try:
                ans[f.name] = Post(f)
            except ValueError:
                print(f'NOT FOUND: {f.name}')
    return ans


def post_category_dataframe():
    ans = post_factory()
    uber = []
    for k, post in ans.items():
        uber.extend(post.rows_by_category())
    df = pd.DataFrame(uber, columns=['link', 'posted', 'category'])
    return df


def post_dataframe(ans=None):
    df = post_dataframe_raw(ans)
    return df[['directory', 'name', 'category', 'size', 'posted',
               'images', 'tables', 'tikz', 'bibtex']]


def post_dataframe_raw(dev=False, ans=None):
    """
    ans = post_factory()
    post_dataframe(ans)

    """
    if ans is None:
        ans = post_factory(dev)
    df = pd.DataFrame([post.row() for post in ans.values()],
                      columns=Post.columns())

    # this is formatting really...
    df['modified'] = df.modified.dt.strftime('%Y-%m-%d  %H:%M:%S')
    df['size'] = df['size'].apply(lambda x: f"{x:,d}")

    return df


def post_meta_page(out_dir=''):
    """
    Create a page with a table of posts
    """

    out_dir = BLOG_BASE / 'meta'

    today = datetime.today().strftime('%Y-%m-%d')
    ans = post_factory()
    df = post_dataframe_raw()
    df = df.drop(columns=['directory', 'name', 'modified'])
    dfstr = df.to_html(index=False, escape=False, table_id='BlogTable')

    header = """---
author: "Stephen J. Mildenhall"
title: "{title}"-
description: "{description}"
date: "{date}"
date-modified: last-modified
categories: {categories}
draft: false
---

<style>
    td {{
      font-size: 0.5em;
    }}
</style>

{contents}

"""

    scripts = """
<script src="https://code.jquery.com/jquery-3.5.1.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@4.5.2/dist/js/bootstrap.bundle.min.js"></script>
<script type="text/javascript" charset="utf8" src="https://cdn.datatables.net/1.11.3/js/jquery.dataTables.js"></script>
<script>
    $(document).ready(function() {
        var table = $('#BlogTable').DataTable({
        "pageLength": 25,
        "order": [[ 3, "desc" ]],
        "columnDefs": [
            {
                "render": function(data, type, row) {
                    return parseInt(data);
                },
                "targets": [4, 5, 6]  // this targets columns 4-6 to be ints
            }
        ]
        });
    });
</script>

"""

    page = header.format(title='Blog Contents',
                         date=today,
                         categories='[meta]',
                         description='Searchable table of all blog posts.',
                         contents=dfstr
                         ) + scripts
    p = BLOG_BASE / f'meta/Blog-Contents'
    p.mkdir(exist_ok=True)
    pi = p / 'index.qmd'
    if pi.exists():
        pi.unlink()
    pi.write_text(page, encoding='utf-8')


# from blog tools ====================================================================
def run_command(command, flag=True):
    """
    Run a command and show results. Allows for weird xx behavior

    :param command:
    :param flag:
    :return:
    """
    with Popen(command, stdout=PIPE, stderr=PIPE, universal_newlines=True) as p:
        line1 = p.stdout.read()
        line2 = p.stderr.read()
        exit_code = p.poll()
        if line1:
            logger.info('\n' + line1[-250:])
        if line2:
            if flag:
                raise ValueError(line2)
            else:
                logger.info(line2)
    return exit_code


def _get_file_timestamp(file_path):
    """Returns the last modification timestamp of a file."""
    return file_path.stat().st_mtime


def render_modified_posts(execute=False):
    """Checks for modified posts and calls Quarto render for them."""
    update = []
    for post_file in BLOG_BASE.glob('**/*.qmd'):
        output_path = OUTPUT_DIR / \
            post_file.with_suffix(".html").name  # Construct output path

        if not output_path.exists() or _get_file_timestamp(post_file) > _get_file_timestamp(output_path):
            update.append(str(post_file.relative_to(BLOG_BASE.parent).parent))

    if len(update) == 0:
        print('No files to update')
    else:
        print(f'Update\n{update}')
        cmd = ["quarto", "render"]
        cmd.extend(update)
        if execute:
            run_command(cmd)


class TeXMacros():
    """
    A class for dealing with TeX macros

    made out of PublisherBase in blog_tools.py
    from great2.blog
    """
    _macros = r"""\def\E{\mathsf{E}}
\def\Var{\mathsf{Var}}
\def\var{\mathsf{var}}
\def\SD{\mathsf{SD}}
\def\VaR{\mathsf{VaR}}
\def\CTE{\mathsf{CTE}}
\def\WCE{\mathsf{WCE}}
\def\AVaR{\mathsf{AVaR}}
\def\CVaR{\mathsf{CVaR}}
\def\TVaR{\mathsf{TVaR}}
\def\biTVaR{\mathsf{biTVaR}}
\def\ES{\mathsf{ES}}
\def\EPD{\mathsf{EPD}}
\def\cov{\mathsf{cov}}
\def\corr{\mathsf{Corr}}
\def\Pr{\mathsf{Pr}}
\def\ecirc{\accentset{\circ} e}
\def\dsum{\displaystyle\sum}
\def\dint{\displaystyle\int}
\def\AA{\mathcal{A}}
\def\bb{\bm{b}}
\def\ww{\bm{w}}
\def\xx{\bm{x}}
\def\yy{\bm{y}}
\def\HH{\bm{H}}
\def\FFF{\mathscr{F}}
\def\FF{\mathcal{F}}
\def\MM{\mathcal{M}}
\def\OO{\mathscr{O}}
\def\PPP{\mathscr{P}}
\def\PP{\mathsf{P}}
\def\QQ{\mathsf{Q}}
\def\RR{\mathbb{R}}
\def\ZZ{\mathbb{Z}}
\def\NN{\mathbb{N}}
\def\XXX{\mathcal{X}}
\def\XX{\bm{X}}
\def\ZZZ{\mathcal{Z}}
\def\bbeta{\bm{\beta}}
\def\cp{\mathsf{CP}}
\def\atan{\mathrm{atan}}
\def\ecirc{\accentset{\circ} e}
\def\tpx{{{}_tp_x}}
\def\kpx{{{}_kp_x}}
\def\tpy{{{}_tp_y}}
\def\tpxy{{{}_tp_{xy}}}
\def\tpxybar{{{}_tp_{\overline{xy}}}}
\def\tqx{{{}_tq_x}}"""

    @staticmethod
    def process_tex_macros(md_in, report=False):
        """
        Expand standard general.tex macros in the md_in text blog

        If ``additional_macros is not None`` then use it to update the standard list

        If ``report is True`` then just return the dictionary of macro substitutions
        """
        m, regex = TeXMacros.tex_to_dict(TeXMacros._macros)
        if report is True:
            return m, regex

        md_in, n = re.subn(regex, lambda x: m.get(
            x[0]), md_in, flags=re.MULTILINE)
        # lcroof is not handled

        return md_in, n

    @staticmethod
    def convert_pdfs(dir_name, output_folder='', pattern='*.pdf', format='png', dpi=200, transparent=True):
        """
        Bulk conversion of all pdfs in dir_name to png. Linux (pdf2image) only. Pre-run!
        Does not adjust names in the text.

        """
        if type(dir_name) == str:
            dir_name = Path(dir_name)

        if output_folder == '':
            output_folder = dir_name

        for f in dir_name.glob(pattern):
            fo = f.stem
            logger.info(f'converting {f.name} to {fo}')
            convert_from_path(str(f), dpi=dpi, output_folder=output_folder, fmt=format, transparent=transparent,
                              output_file=fo, single_file=True)

    @staticmethod
    def tex_to_dict(text):
        """
        Convert text, a series of def{} macros into a dictionary
        returns the dictionary and the regex of all keys
        """
        smacros = text.split('\n')
        smacros = [TeXMacros.tex_splitter(i) for i in smacros]
        m = {i: j for (i, j) in smacros}
        regex = '|'.join([re.escape(k) for k in m.keys()])
        return m, regex

    @staticmethod
    def tex_splitter(x):
        """
        x is a single def style tex macro
        """
        x = x.replace('\\def', '')
        i = x.find('{')
        return x[:i], x[i + 1:-1]


class AddBlogPost(TeXMacros):

    def __init__(self, file_in, categories, title='', dev=True, execute=False):
        """
        AddBlogPost works on a Steve-style markdown file, with @@@ includes
        and images relative to the current md file location. It

        * fixes tex macros
        * fixes links to images, creating svg for pdfs if necessary
        * creates yaml header
        * adds categories
        * figures title from yaml or uses input title
        * saves to correct location

        If dev is not '' it is the directory to save to. This avoids
        polluting the main blog when you are just messing around.

        Usage (from Jupyter)::

            # one stop shop
            post = AddBlogPost(filename, ['categories'],
            title='', dev=True, execute=True')

            # if execute=False then manually run the process
            post.process()   # includes and tex macros
            post.adjust_image_links()
            post.save(dev=True)

        For example, to load the CEA files::

            p1 = Path('C:\\Users\\steve\\S\\TELOS\\Archive\\CEACaseStudy\\Notes\\CEA-very-short.md')
            p2 = Path('C:\\Users\\steve\\S\\TELOS\\Archive\\CEACaseStudy\\Notes\\CEA-short.md')
            ps = [p1, p2]
            titles = ['ERM Saves the Day for the CEA',
                      'ERM Saves the Day for the CEA v2']
            p1.exists(), p2.exists()

            for p, t in zip(ps, titles):
                post = blog.AddBlogPost(p,
                                    categories=['research', 'pricing'],
                                    title=t,
                                    dev=False,
                                    execute=True)

        """
        self.file_in = Path(file_in)
        self.source_dir = self.file_in.parent.resolve()
        self.categories = categories
        self.dev = dev

        # split into processed yaml and txt part, text is whole doc
        self.text = self.file_in.read_text(encoding='utf-8')
        parts = self.text.split('---', 2)
        try:
            if len(parts) > 2:
                self.yaml = yaml.safe_load(parts[1])
                self.txt = parts[2]
            else:
                print(f'parse split has too few parts {parts}')
        except yaml.YAMLError as exc:
            raise ValueError(f"Error parsing YAML: {exc}")
        except Exception as e:
            raise ValueError(f"Error reading index file: {e}")
        if title == '':
            self.title = self.yaml.get('title', '')
        else:
            self.title = title
        self.date = self.yaml.get(
            'date', datetime.today().strftime('%Y-%m-%d'))
        if len(self.date) > 10:
            # assume
            # created YYYY-MM-DD TTTTT
            self.date = self.date.split(' ')[1]
        self.subtitle = self.yaml.get('subtitle', '')
        if dev != '':
            post_dir = Path(dev)
        else:
            post_dir = BLOG_BASE
        title = self.title.replace(' ', '-')
        title = f'{self.date}-{title}'
        post_dir = post_dir / self.categories[0]
        post_dir = post_dir / title
        post_dir.mkdir(exist_ok=True, parents=True)
        self.post_dir = post_dir
        self.file = post_dir / "index.qmd"
        # for adjusting images
        self.img_path = post_dir / 'img'
        self.img_path.mkdir(exist_ok=True)

        if execute:
            # one stop shop
            self.process()
            self.adjust_image_links()
            self.save()

    def save(self):
        """
        Run with execute=False to set the directories, get title etc.

        """
        header = {'title': self.title,
                  'categories': self.categories,
                  'date': self.date,
                  'author': 'Stephen J. Mildenhall',
                  'description': '',
                  'draft': False}
        if self.subtitle != '':
            header['subtitle'] = self.subtitle

        out = '\n'.join(
            ['---', yaml.dump(header).strip(), '---\n', self.txt])

        self.file.write_text(out, encoding='utf-8')
        print(f'{len(out):,d} chars written to {self.file}')

    def process(self):
        self.process_includes()
        self.txt, n = self.process_tex_macros(self.txt)
        if n:
            print(f'Replaced {n} TeX macros')

    def process_includes(self):
        """
        Adjusts self.txt, the body text
        """
        txt = self.txt

        if txt.find('@@@') < 0:
            return
        # else have work to do

        fn = self.file_in
        base_dir = fn.parent.resolve()
        n_includes = 0
        # first, substitute for all NNN specs (keep this for backwards compatibility)
        # assumes you are in the current directory
        file_map = {i.name[0:3]: i for i in base_dir.parent.glob("*.md")}
        txt, n_includes = AddBlogPost._process_includes(
            txt, base_dir, n_includes, file_map)
        self.txt = txt

    @staticmethod
    def _process_includes(txt, base_dir, n_includes, file_map):
        """
        Process @@@ include elements.
        From markdown_make.py without color_includes logic

        Iterative processing of include files
        file_map looks for nnn_something.md files in the current directory
        base_dir = directory name
        """

        includes = re.findall(
            r'@@@include ([\./]*)([0-9]{3}|[0-9A-Za-z])([^\n]+\.[a-z]+)?', txt)
        for res_ in includes:
            original_match = ''.join(res_)
            # logger.info(res_, file_map)
            # res_[1] looks for nnn type files and tries to find them in file_map
            if res_[2] == '':
                res = file_map[res_[1]]
                # logger.info(f'REPLACING {res_} with {res}')
            else:
                res = original_match
                # logger.info(f'using {"".join(res_)} as {res}')
            n_includes += 1
            try:
                repl = (base_dir / res).read_text(encoding='utf-8')
                repl = AddBlogPost._strip_yaml(repl)
                repl, n_includes = AddBlogPost._process_includes(
                    repl, base_dir, n_includes, file_map)
                txt = txt.replace(f'@@@include {original_match}', repl)
            except FileNotFoundError:
                raise FileNotFoundError(res)
        return txt, n_includes

    @staticmethod
    def _strip_yaml(text):
        """
        Strip starging yaml, between first --- and next --- from text.
        Applies to included files.
        From markdown_make.py.

        :param text:
        :return:
        """
        if text[:3] != '---':
            return text
        else:
            stext = text.split('\n')
            stext.pop(0)
            n = 0
            for ln in stext:
                if ln != '---':
                    n += 1
                else:
                    n += 1
                    return '\n'.join(stext[n:])

    def adjust_image_links(self):
        """
        Convert pdf figure links. DOES NOT MAKE the new images (that needs pdf2image (Linux)); it looks
        for linkely contenders and selects one.

        Completely separate from dealing with tikz.

        Looks in the same folder for an appropriate non-pdf version of the file: prefers SVG then PNG then JPG.

        If no file found then sets link to ``default`` format and it is up to you to create that file (noted
        in the workflow).

        Note, these file names are futher tinkered to move them to the website static folder.

        See git history for an attempt to use divsvgm -P filename conversion...but those svg files do not
        render.

        """
        txt = self.txt
        # need to look for images and copy them over; _file_renamer does a lot of work
        if txt.find('![') < 0:
            print('No image links found')

        # find candidates - lock in since you will be changing txt
        matches = list(re.findall(
            r'(!\[((?:.|\n)*?)\]\((.+?)\))(\{.*?\})?', txt))
        for whole_match, caption, file_name, classes in matches:
            image_file = self.source_dir / file_name
            if file_name[:4] == 'http':
                # external link - not adjusted
                print(f'IMAGE: External link unadjusted: {file_name}')
                continue
            elif image_file.exists() is True and image_file.suffix != '.pdf':
                print(f'IMAGE: Non PDF link unadjusted: {file_name}')
                new_file = image_file
            elif image_file.exists() is False:
                # this is just a general problem...should not occur often
                print(
                    f'IMAGE: Image file does not exist: leaving link unchanged for {file_name}')
                continue
            else:
                # file exists and is a pdf...we find a replacement (default leave as PDF)
                # look for candidate replacement file
                for kind in ['.svg', '.png', '.jpg']:
                    new_file = image_file.with_suffix(kind)
                    if new_file.exists() and new_file.stat().st_mtime >= image_file.stat().st_mtime:
                        new_file = image_file.with_suffix(kind)
                        break
                else:
                    # did not find an alternative, but still need to copy the pdf over
                    # new_file = image_file
                    # OK, make an SVG...
                    new_file = image_file.with_suffix('.svg')
                    print(
                        f'IMAGE: Creating svg file for {image_file.name} (using new pdf2svg util)')
                    # https://github.com/jalios/pdf2svg-windows
                    command = [
                        'C:\\temp\\pdf2svg-windows\\dist-64bits\\pdf2svg', str(image_file), str(new_file)]
                    run_command(command)

            # copy over new file, which by construction must exist
            # create link to new file
            web_file = (self.img_path / new_file.name)
            if web_file.exists():
                web_file.unlink()
            # safe rather than sorry on re-creating the link
            print(f'IMAGE: Creating link {web_file} for {file_name}')
            web_file.hardlink_to(new_file)

            # link for the website, relative to the base of the blog
            link_name = web_file.relative_to(web_file.parent.parent).as_posix()
            # finally, have to adjust the link name and add 100% width ; classes includes the braces
            txt = txt.replace(f'({file_name}){classes}',
                              f'({link_name}){{width=100%}}')
            print(
                f'IMAGE: txt image link  ![]({file_name}) replaced with ![...]({link_name})')
            if classes == '':
                print('IMAGE:>>>class {{width=100%}} added')
            else:
                print(
                    f'IMAGE:>>>class {classes} replaced with {{width=100%}}')

        self.txt = txt


class TikzBase():
    _tex_template = """\\documentclass[10pt, border=5mm]{{standalone}}

% needs lualatex - uncomment for Wiley fonts
%\\usepackage{{fontspec}}
%\\setmainfont{{Stix Two Text}}
%\\usepackage{{unicode-math}}
%\\setmathfont{{Stix Two Math}}

\\usepackage{{url}}
\\usepackage{{tikz}}
\\usepackage{{color}}
\\usetikzlibrary{{arrows,calc,positioning,shadows.blur,decorations.pathreplacing}}
\\usetikzlibrary{{automata}}
\\usetikzlibrary{{fit}}
\\usetikzlibrary{{snakes}}
\\usetikzlibrary{{intersections}}
\\usetikzlibrary{{decorations.markings,decorations.text,decorations.pathmorphing,decorations.shapes}}
\\usetikzlibrary{{decorations.fractals,decorations.footprints}}
\\usetikzlibrary{{graphs}}
\\usetikzlibrary{{matrix}}
\\usetikzlibrary{{shapes.geometric}}
\\usetikzlibrary{{mindmap, shadows}}
\\usetikzlibrary{{backgrounds}}
\\usetikzlibrary{{cd}}

% really common macros
\\newcommand{{\\I}}{{\\vphantom{{lp}}}}  % fka grtspacer

\\def\\dfrac{{\\displaystyle\\frac}}
\\def\\dint{{\\displaystyle\\int}}

\\begin{{document}}

{tikz_begin}{tikz_code}{tikz_end}

\\end{{document}}
"""

    @staticmethod
    def split_tikz(txt):
        """
        Split text to get the tikzpicture. Format is

        initial text pip then groups of four:

        1. begin tag ``(1::4)``
        2. tikz code ``(2::4)``
        3. end tag   ``(3::4)``
        4. non-related text ``(4::4)``

        """
        return re.split(r'(\\begin{tikz(?:cd|picture)}|\\end{tikz(?:cd|picture)})', txt)


class TikzConverter(Post, TikzBase):
    #     _tex_template = """\\documentclass[10pt, border=5mm]{{standalone}}

    # % needs lualatex - uncomment for Wiley fonts
    # %\\usepackage{{fontspec}}
    # %\\setmainfont{{Stix Two Text}}
    # %\\usepackage{{unicode-math}}
    # %\\setmathfont{{Stix Two Math}}

    # \\usepackage{{url}}
    # \\usepackage{{tikz}}
    # \\usepackage{{color}}
    # \\usetikzlibrary{{arrows,calc,positioning,shadows.blur,decorations.pathreplacing}}
    # \\usetikzlibrary{{automata}}
    # \\usetikzlibrary{{fit}}
    # \\usetikzlibrary{{snakes}}
    # \\usetikzlibrary{{intersections}}
    # \\usetikzlibrary{{decorations.markings,decorations.text,decorations.pathmorphing,decorations.shapes}}
    # \\usetikzlibrary{{decorations.fractals,decorations.footprints}}
    # \\usetikzlibrary{{graphs}}
    # \\usetikzlibrary{{matrix}}
    # \\usetikzlibrary{{shapes.geometric}}
    # \\usetikzlibrary{{mindmap, shadows}}
    # \\usetikzlibrary{{backgrounds}}
    # \\usetikzlibrary{{cd}}

    # % really common macros
    # \\newcommand{{\\grtspacer}}{{\\vphantom{{lp}}}}

    # \\def\\dfrac{{\\displaystyle\\frac}}
    # \\def\\dint{{\\displaystyle\\int}}

    # \\begin{{document}}

    # {tikz_begin}{tikz_code}{tikz_end}

    # \\end{{document}}
    # """

    def __init__(self, post, tex_engine='pdflatex'):
        """
        AddBlogPost works on the original steve-style markdown file, with @@@ includes
        and images relative to the current md file location.

        TikzConverter will

        * find tikz blocks
        * extract them and save them to a tikz folder (so they can be edited)
        * create a pdf and svg from the tikz blob
        * replace the block with a link to the image and a comment explaining
          what has happened.

        It takes a Post object as an argument and wraps it.

        post = an AddBlogPost object

        Code works but is not beautiful..

        lualatex is more robust, but slower...
        pdflatex can't handle the fancy wiley fonts

        """
        self.post_instance = post
        self.tex_engine = tex_engine
        # directory for TeX and images
        self.tikz_path = self.post_dir / 'tikz'
        self.tikz_path.mkdir(exist_ok=True)

    def __getattr__(self, name):
        """
        Delegate attribute access to the Post instance if attribute not found,
        see blog.mynl.com/http:/blog.mynl.com/posts/programming/Effective-Python/2024-02-13-Classes

        """
        return getattr(self.post_instance, name)

    # @staticmethod
    # def split_tikz(txt):
    #     """
    #     Split text to get the tikzpicture. Format is

    #     initial text pip then groups of four:

    #     1. begin tag ``(1::4)``
    #     2. tikz code ``(2::4)``
    #     3. end tag   ``(3::4)``
    #     4. non-related text ``(4::4)``

    #     """
    #     return re.split(r'(\\begin{tikz(?:cd|picture)}|\\end{tikz(?:cd|picture)})', txt)

    def split_figures(self):
        return re.split(r'(\\begin{figure}|\\begin{sidewaysfigure}|\\begin{table}|'
                        r'\\end{figure}|\\end{sidewaysfigure}|\\end{table})', self.txt)

    def list_tikz(self):
        """
        List the figures in doc_fn
        """
        return self.split_tikz(self.txt)[2::4]

    def process_tikz(self):
        """
        Process the tikz figures/tables/sidewaystables in the doc into svg files.
        """
        all_containers = self.split_figures()
        begin_tags = iter(all_containers[1::4])
        outer_codes = iter(all_containers[2::4])
        end_tags = iter(all_containers[3::4])
        # next_blob = iter(all_containers[4::4])

        for i, begin_tag, outer_code, end_tag in zip(count(), begin_tags, outer_codes, end_tags):
            # find tikzpicture, tikzcd etc.
            if outer_code.find('\\begin{tikz') >= 0:
                # container contains a tikzpicture
                caption = re.search(
                    r'\\caption\{((?:.|\n)*?)\}\n', outer_code, flags=re.MULTILINE)
                if caption is None:
                    caption = ''
                else:
                    caption = caption[1]
                # adjust the original doc
                # will create a tex file, tex it to pdf, create svg file
                # unlike in blog tools, the svg file is created in the correct
                # place, so no need for subsequent links
                svg_path = self.tikz_path / f'tikz.{i+1}.svg'
                tex_path = svg_path.with_suffix('.tex')
                # this is a string link for the output post
                web_link = svg_path.relative_to(
                    svg_path.parent.parent).as_posix()
                if begin_tag.find('figure') > 0:
                    lbl = f'*Figure {i+1}:*'
                else:
                    lbl = f'*Table {i+1}:*'
                replacement_text = '\n'.join([
                    "<!--",
                    "tikz diagram replaced with svg by TikzConverter",
                    f'Original tex in {tex_path}',
                    '-->'
                    f"\n\n![{lbl} {caption}]({web_link}){{width=75%}}\n\n"
                ])

                self.txt = self.txt.replace(
                    f'{begin_tag}{outer_code}{end_tag}',
                    replacement_text
                )
                # do not have to worry about existing classes - this was a figure or table...
                print(
                    f'TIKZ: replaced text for {begin_tag}...{end_tag} with ![...]({web_link})')
                # process if the svg files is older than the index file
                if svg_path.exists() and \
                        svg_path.stat().st_mtime >= self.index_file.stat().st_mtime:
                    print(
                        f'TIKZ: using existing newer svg file for Tikz #{i}, {svg_path.name}')
                else:
                    # make tex code for a stand-alone document
                    tikz_begin, tikz_code, tikz_end = self.split_tikz(outer_code)[
                        1:4]
                    tex_code = self._tex_template.format(
                        tikz_begin=tikz_begin, tikz_code=tikz_code, tikz_end=tikz_end)
                    tex_path.write_text(tex_code, encoding='utf-8')
                    print(
                        f'TIKZ: diagram #{i}, created temp file = {tex_path.name}')
                    pdf_file = tex_path.with_suffix('.pdf')
                    print(f'TIKZ: Update pdf file for Tikz #{i}')
                    if self.tex_engine == 'pdflatex':
                        # faster with template
                        # TODO EVID hard coded template
                        template = str(
                            Path.home() / 'S/TELOS/Blog/format/tikz.fmt')
                        command = ['pdflatex', f'--fmt={template}',
                                   f'--output-directory={str(tex_path.parent.resolve())}',
                                   str(tex_path.resolve())]
                    else:
                        # for STIX fonts, no template
                        command = ['lualatex',
                                   f'--output-directory={str(tex_path.parent.resolve())}',
                                   str(tex_path.resolve())]
                    print(f'TIKZ: TeX Command={" ".join(command)}')
                    run_command(command)
                    # to recreate
                    (tex_path.parent /
                     f'make_{i+1}.bat').write_text(" ".join(command))
                    print(
                        f'TIKZ: Creating svg file for Tikz #{i+1} (using new pdf2svg util)')
                    # https://github.com/jalios/pdf2svg-windows
                    command = [
                        'C:\\temp\\pdf2svg-windows\\dist-64bits\\pdf2svg', str(pdf_file.resolve()), str(svg_path.resolve())]
                    # seems to return info on stderr?
                    print(f'PDF->SVG: {" ".join(command)}')
                    run_command(command, flag=False)


class TikzProcessor(TikzBase):

    def __init__(self, file, tex_engine='pdflatex'):
        """
        TikzProcessor (from TikzConvertyer): process a tz file into svg. It

        * creates a pdf and svg from the tikz blob

        lualatex is more robust, but slower...
        pdflatex can't handle the fancy wiley fonts

        """
        self.file = Path(file)
        if not self.file.exists():
            raise FileNotFoundError(f'Error: {file} does not exist.')
        self.txt = self.file.read_text(encoding='utf-8')
        self.tex_engine = tex_engine
        # directory for TeX and images
        self.out_path = self.file.resolve().parent.parent / 'img'
        self.out_path.mkdir(exist_ok=True)

    def process_tikz(self, verbose=False):
        """
        Process the tikz into pdf and svg
        """
        outer_code = self.txt

        if outer_code.find('\\begin{tikz') >= 0:
            # container contains a tikzpicture
            svg_path = self.out_path / (self.file.stem + '.svg')
            tex_path = self.file.with_suffix('.tex')

            # make tex code for a stand-alone document
            tikz_begin, tikz_code, tikz_end = self.split_tikz(outer_code)[
                1:4]
            tex_code = self._tex_template.format(
                tikz_begin=tikz_begin, tikz_code=tikz_code, tikz_end=tikz_end)
            tex_path.write_text(tex_code, encoding='utf-8')
            print(
                f'TIKZ: created temp file = {tex_path.name}')
            pdf_file = tex_path.with_suffix('.pdf')
            print(f'TIKZ: Update pdf file')
            if self.tex_engine == 'pdflatex':
                # faster with template
                # TODO EVID hard coded template
                template = str(
                    Path.home() / 'S/TELOS/Blog/format/tikz.fmt')
                command = ['pdflatex', f'--fmt={template}',
                           f'--output-directory={str(tex_path.parent.resolve())}',
                           str(tex_path.resolve())]
            else:
                # for STIX fonts, no template
                command = ['lualatex',
                           f'--output-directory={str(tex_path.parent.resolve())}',
                           str(tex_path.resolve())]
            if verbose:
                print(f'TIKZ: TeX Command={" ".join(command)}')
            run_command(command)
            # to recreate
            (tex_path.parent /
             f'make_tikz.bat').write_text(" ".join(command))
            if verbose:
                print(
                    f'TIKZ: Creating svg file for Tikz (using new pdf2svg util)')
            # https://github.com/jalios/pdf2svg-windows
            command = [
                'C:\\temp\\pdf2svg-windows\\dist-64bits\\pdf2svg',
                str(pdf_file.resolve()), str(svg_path.resolve())]
            # seems to return info on stderr?
            if verbose:
                print(f'PDF->SVG: {" ".join(command)}')
            run_command(command, flag=False)
            if not verbose:
                # tidy up
                tex_path.unlink()
                tex_path.with_suffix('.aux').unlink()
                tex_path.with_suffix('.log').unlink()
                pdf_file.unlink()


def blog_new_post_work(title, categories, date='', description='', image='', csl='', draft=False):
    """
    Create a new page for the blog. This is a one-time operation, so it is not
    in the class.

    """

    assert len(categories) > 0, 'Categories must be non-empty'

    if date == '':
        date = datetime.today().strftime('%Y-%m-%d')

    header = {
        'author': 'Stephen J. Mildenhall',
        'title': title,
        'description': description,
        'date': date,
        'date-modified': 'last-modified',
        'categories': categories,
        'draft': draft,
        'image': 'img/banner.png'
    }
    if image != '':
        header['image'] = image
    if csl == 'jru':
        header['csl'] = "../../../static/journal-of-risk-and-uncertainty.csl"
    elif csl != '':
        header['csl'] = csl

    out = '\n'.join(['---', yaml.dump(header).strip(), '---\n',
                    "\n\n![](img/banner.png)\n\nPOST TEXT HERE"])

    post_dir = BLOG_BASE / categories[0] / f'{date}-{title.replace(" ", "-")}'
    post_dir.mkdir(exist_ok=True, parents=True)
    (post_dir / 'img').mkdir(exist_ok=True)
    file = post_dir / "index.qmd"
    file.write_text(out, encoding='utf-8')
