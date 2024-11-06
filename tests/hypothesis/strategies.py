# Copyright (C) 2024  Christian Ledermann
#
# This library is free software; you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License as published by the Free
# Software Foundation; either version 2.1 of the License, or (at your option)
# any later version.
#
# This library is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more
# details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this library; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301 USA

"""Custom hypothesis strategies for testing."""
import re
import string
from functools import partial
from typing import Final
from urllib.parse import urlencode

from hypothesis import strategies as st

ID_TEXT: Final = string.ascii_letters + string.digits + ".-_"
nc_name = partial(
    st.from_regex,
    regex=re.compile(r"^[A-Za-z_][\w.-]*$"),
    alphabet=ID_TEXT,
    fullmatch=True,
)

href_langs = partial(
    st.from_regex,
    regex=re.compile(r"^[a-zA-Z]{1,8}(-[a-zA-Z0-9]{1,8})?$"),
    alphabet=f"{string.ascii_letters}-{string.digits}",
    fullmatch=True,
)
media_types = partial(
    st.from_regex,
    regex=re.compile(r"^[a-zA-Z0-9-]+/[a-zA-Z0-9-]+$"),
    alphabet=f"{string.ascii_letters}/-{string.digits}",
    fullmatch=True,
)
xml_text = partial(
    st.text,
    alphabet=st.characters(min_codepoint=1, blacklist_categories=("Cc", "Cs")),
)


@st.composite
def query_strings(draw: st.DrawFn) -> str:
    params = draw(
        st.dictionaries(
            keys=st.text(alphabet=string.ascii_letters, min_size=1),
            values=st.text(alphabet=string.printable),
        ),
    )
    return urlencode(params)