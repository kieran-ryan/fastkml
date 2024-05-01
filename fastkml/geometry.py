# Copyright (C) 2012 - 2024 Christian Ledermann
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

import logging
import re
from functools import partial
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import Union
from typing import cast

import pygeoif.geometry as geo
from pygeoif.exceptions import DimensionError
from pygeoif.factories import shape
from pygeoif.types import GeoCollectionType
from pygeoif.types import GeoType
from pygeoif.types import LineType
from pygeoif.types import Point2D
from pygeoif.types import Point3D

from fastkml import config
from fastkml.base import _BaseObject
from fastkml.base import _XMLObject
from fastkml.enums import AltitudeMode
from fastkml.enums import Verbosity
from fastkml.exceptions import KMLParseError
from fastkml.exceptions import KMLWriteError
from fastkml.helpers import bool_subelement
from fastkml.helpers import enum_subelement
from fastkml.helpers import subelement_bool_kwarg
from fastkml.helpers import subelement_enum_kwarg
from fastkml.helpers import xml_subelement
from fastkml.helpers import xml_subelement_kwarg
from fastkml.registry import RegistryItem
from fastkml.registry import known_types
from fastkml.registry import registry
from fastkml.types import Element

__all__ = [
    "AnyGeometryType",
    "Coordinates",
    "GeometryType",
    "LineString",
    "LinearRing",
    "MultiGeometry",
    "MultiGeometryType",
    "Point",
    "Polygon",
    "create_multigeometry",
]

logger = logging.getLogger(__name__)

GeometryType = Union[geo.Polygon, geo.LineString, geo.LinearRing, geo.Point]
MultiGeometryType = Union[
    geo.MultiPoint,
    geo.MultiLineString,
    geo.MultiPolygon,
    geo.GeometryCollection,
]
AnyGeometryType = Union[GeometryType, MultiGeometryType]


def handle_invalid_geometry_error(
    *,
    error: Exception,
    element: Element,
    strict: bool,
) -> None:
    error_in_xml = config.etree.tostring(  # type: ignore[attr-defined]
        element,
        encoding="UTF-8",
    ).decode(
        "UTF-8",
    )
    msg = f"Invalid coordinates in '{error_in_xml}' caused by '{error}'"
    logger.error(msg)
    if strict:
        raise KMLParseError(msg) from error


def coordinates_subelement(
    obj: _XMLObject,
    *,
    element: Element,
    attr_name: str,
    node_name: str,
    precision: Optional[int],
    verbosity: Optional[Verbosity],
) -> None:
    """
    Set the value of an attribute from a subelement with a text node.

    Args:
    ----
        obj (_XMLObject): The object from which to retrieve the attribute value.
        element (Element): The parent element to add the subelement to.
        attr_name (str): The name of the attribute to retrieve the value from.
        node_name (str): The name of the subelement to create.
        precision (Optional[int]): The precision of the attribute value.
        verbosity (Optional[Verbosity]): The verbosity level.

    Returns:
    -------
        None

    """
    if getattr(obj, attr_name, None):
        p = precision if precision is not None else 6
        coords = getattr(obj, attr_name)
        if len(coords[0]) == 2:
            tuples = (f"{c[0]:.{p}f},{c[1]:.{p}f}" for c in coords)
        elif len(coords[0]) == 3:
            tuples = (f"{c[0]:.{p}f},{c[1]:.{p}f},{c[2]:.{p}f}" for c in coords)
        else:
            msg = f"Invalid dimensions in coordinates '{coords}'"
            raise KMLWriteError(msg)
        element.text = " ".join(tuples)


def subelement_coordinates_kwarg(
    *,
    element: Element,
    ns: str,
    name_spaces: Dict[str, str],
    node_name: str,
    kwarg: str,
    classes: Tuple[known_types, ...],
    strict: bool,
) -> Dict[str, LineType]:
    # Clean up badly formatted tuples by stripping
    # space following commas.
    try:
        latlons = re.sub(r", +", ",", element.text.strip()).split()
    except AttributeError:
        return {}
    try:
        return {
            kwarg: [  # type: ignore[dict-item]
                tuple(float(c) for c in latlon.split(",")) for latlon in latlons
            ],
        }
    except ValueError as error:
        handle_invalid_geometry_error(
            error=error,
            element=element,
            strict=strict,
        )
        return {}


class Coordinates(_XMLObject):
    """
    Represents a set of coordinates in decimal degrees.

    Attributes
    ----------
        coords (LineType): A list of tuples representing the coordinates.
            Each coord consists of floating point values for
            longitude, latitude, and altitude.
            The altitude component is optional.
            Coordinates are expressed in decimal degrees only.

    """

    _default_ns = config.KMLNS
    coords: LineType

    def __init__(
        self,
        *,
        ns: Optional[str] = None,
        name_spaces: Optional[Dict[str, str]] = None,
        coords: Optional[LineType] = None,
        **kwargs: Any,
    ):
        super().__init__(ns=ns, name_spaces=name_spaces, **kwargs)
        self.coords = coords or []

    def __repr__(self) -> str:
        """Create a string (c)representation for Coordinates."""
        return (
            f"{self.__class__.__module__}.{self.__class__.__name__}("
            f"ns={self.ns!r}, "
            f"name_spaces={self.name_spaces!r}, "
            f"coords={self.coords!r}, "
            f"**kwargs={self._get_splat()!r},"
            ")"
        )

    def __bool__(self) -> bool:
        return bool(self.coords)

    @classmethod
    def get_tag_name(cls) -> str:
        """Return the tag name."""
        return cls.__name__.lower()


registry.register(
    Coordinates,
    item=RegistryItem(
        classes=(LineType,),  # type: ignore[arg-type]
        attr_name="coords",
        node_name="coordinates",
        get_kwarg=subelement_coordinates_kwarg,
        set_element=coordinates_subelement,
    ),
)


class _Geometry(_BaseObject):
    """
    Baseclass with common methods for all geometry objects.

    Attributes: extrude: boolean --> Specifies whether to connect the feature to
                                     the ground with a line.
                tessellate: boolean -->  Specifies whether to allow the LineString
                                         to follow the terrain.
                altitudeMode: --> Specifies how altitude components in the <coordinates>
                                  element are interpreted.

    """

    extrude: Optional[bool]
    tessellate: Optional[bool]
    altitude_mode: Optional[AltitudeMode]
    _geometry: Optional[AnyGeometryType]

    def __init__(
        self,
        *,
        ns: Optional[str] = None,
        name_spaces: Optional[Dict[str, str]] = None,
        id: Optional[str] = None,
        target_id: Optional[str] = None,
        extrude: Optional[bool] = None,
        tessellate: Optional[bool] = None,
        altitude_mode: Optional[AltitudeMode] = None,
        geometry: Optional[AnyGeometryType] = None,
        **kwargs: Any,
    ) -> None:
        """

        Args:
        ----
            ns: Namespace of the object
            id: Id of the object
            target_id: Target id of the object
            extrude: Specifies whether to connect the feature to the ground with a line.
            tessellate: Specifies whether to allow the LineString to follow the terrain.
            altitude_mode: Specifies how altitude components in the <coordinates>
                           element are interpreted.

        """
        super().__init__(
            ns=ns,
            id=id,
            name_spaces=name_spaces,
            target_id=target_id,
            **kwargs,
        )
        self.extrude = extrude
        self.tessellate = tessellate
        self.altitude_mode = altitude_mode
        self._geometry = geometry

    def __repr__(self) -> str:
        """Create a string (c)representation for _Geometry."""
        return (
            f"{self.__class__.__module__}.{self.__class__.__name__}("
            f"ns={self.ns!r}, "
            f"name_spaces={self.name_spaces!r}, "
            f"id={self.id!r}, "
            f"target_id={self.target_id!r}, "
            f"extrude={self.extrude!r}, "
            f"tessellate={self.tessellate!r}, "
            f"altitude_mode={self.altitude_mode}, "
            f"geometry={self.geometry!r}, "
            f"**kwargs={self._get_splat()!r},"
            ")"
        )

    def __bool__(self) -> bool:
        return bool(self._geometry)

    @property
    def geometry(self) -> Optional[AnyGeometryType]:
        return self._geometry

    def xx_etree_coordinates(
        self,
        coordinates: Union[Sequence[Point2D], Sequence[Point3D]],
        precision: Optional[int],
    ) -> Element:
        element = cast(
            Element,
            config.etree.Element(f"{self.ns}coordinates"),  # type: ignore[attr-defined]
        )
        if not coordinates:
            return element
        p = precision if precision is not None else 6
        if len(coordinates[0]) == 2:
            tuples = (f"{c[0]:.{p}f},{c[1]:.{p}f}" for c in coordinates)
        elif len(coordinates[0]) == 3:
            tuples = (
                f"{c[0]:.{p}f},{c[1]:.{p}f},{c[2]:.{p}f}"  # type: ignore[misc]
                for c in coordinates
            )
        else:
            msg = (  # type: ignore[unreachable]
                f"Invalid dimensions in coordinates '{coordinates}'"
            )
            raise KMLWriteError(msg)
        element.text = " ".join(tuples)
        return element

    @classmethod
    def _get_coordinates(
        cls,
        *,
        ns: str,
        element: Element,
        strict: bool,
    ) -> Union[List[Point2D], List[Point3D]]:
        """
        Get coordinates from element.

        Coordinates can be any number of tuples separated by a space (potentially any
        number of whitespace characters).
        Values in tuples should be separated by commas with no spaces.

        https://developers.google.com/kml/documentation/kmlreference#coordinates
        """
        coordinates = element.find(f"{ns}coordinates")
        if coordinates is not None:
            # Clean up badly formatted tuples by stripping
            # space following commas.
            try:
                latlons = re.sub(r", +", ",", coordinates.text.strip()).split()
            except AttributeError:
                return []
            try:
                return [  # type: ignore[return-value]
                    tuple(float(c) for c in latlon.split(",")) for latlon in latlons
                ]
            except ValueError as error:
                handle_invalid_geometry_error(
                    error=error,
                    element=element,
                    strict=strict,
                )
        return []

    @classmethod
    def _get_geometry(
        cls,
        *,
        ns: str,
        element: Element,
        strict: bool,
    ) -> Optional[AnyGeometryType]:
        return None

    @classmethod
    def xx_get_kwargs(
        cls,
        *,
        ns: str,
        name_spaces: Optional[Dict[str, str]] = None,
        element: Element,
        strict: bool,
    ) -> Dict[str, Any]:
        kwargs = super()._get_kwargs(
            ns=ns,
            name_spaces=name_spaces,
            element=element,
            strict=strict,
        )
        kwargs.update(
            {"geometry": cls._get_geometry(ns=ns, element=element, strict=strict)},
        )
        return kwargs


registry.register(
    _Geometry,
    item=RegistryItem(
        classes=(bool,),
        attr_name="extrude",
        node_name="extrude",
        get_kwarg=subelement_bool_kwarg,
        set_element=bool_subelement,
    ),
)
registry.register(
    _Geometry,
    item=RegistryItem(
        classes=(bool,),
        attr_name="tessellate",
        node_name="tessellate",
        get_kwarg=subelement_bool_kwarg,
        set_element=bool_subelement,
    ),
)
registry.register(
    _Geometry,
    item=RegistryItem(
        classes=(AltitudeMode,),
        attr_name="altitude_mode",
        node_name="altitudeMode",
        get_kwarg=subelement_enum_kwarg,
        set_element=enum_subelement,
    ),
)


class Point(_Geometry):

    kml_coordinates: Optional[Coordinates]

    def __init__(
        self,
        *,
        ns: Optional[str] = None,
        name_spaces: Optional[Dict[str, str]] = None,
        id: Optional[str] = None,
        target_id: Optional[str] = None,
        extrude: Optional[bool] = None,
        tessellate: Optional[bool] = None,
        altitude_mode: Optional[AltitudeMode] = None,
        geometry: Optional[geo.Point] = None,
        kml_coordinates: Optional[Coordinates] = None,
        **kwargs: Any,
    ) -> None:
        if geometry is not None and kml_coordinates is not None:
            raise ValueError("geometry and kml_coordinates are mutually exclusive")
        if kml_coordinates is None:
            kml_coordinates = (
                Coordinates(coords=geometry.coords)  # type: ignore[arg-type]
                if geometry
                else None
            )
        self.kml_coordinates = kml_coordinates
        super().__init__(
            ns=ns,
            id=id,
            name_spaces=name_spaces,
            target_id=target_id,
            extrude=extrude,
            tessellate=tessellate,
            altitude_mode=altitude_mode,
            # geometry=geometry,
            **kwargs,
        )

    def __repr__(self) -> str:
        """Create a string (c)representation for Point."""
        return (
            f"{self.__class__.__module__}.{self.__class__.__name__}("
            f"ns={self.ns!r}, "
            f"name_spaces={self.name_spaces!r}, "
            f"id={self.id!r}, "
            f"target_id={self.target_id!r}, "
            f"extrude={self.extrude!r}, "
            f"tessellate={self.tessellate!r}, "
            f"altitude_mode={self.altitude_mode}, "
            f"kml_coordinates={self.kml_coordinates!r}, "
            f"**kwargs={self._get_splat()!r},"
            ")"
        )

    def __bool__(self) -> bool:
        return bool(self.kml_coordinates)

    @property
    def geometry(self) -> Optional[geo.Point]:
        if not self.kml_coordinates:
            return None
        return geo.Point.from_coordinates(self.kml_coordinates.coords)


registry.register(
    Point,
    item=RegistryItem(
        classes=(Coordinates,),
        attr_name="kml_coordinates",
        node_name="coordinates",
        get_kwarg=xml_subelement_kwarg,
        set_element=xml_subelement,
    ),
)


class LineString(_Geometry):
    def __init__(
        self,
        *,
        ns: Optional[str] = None,
        name_spaces: Optional[Dict[str, str]] = None,
        id: Optional[str] = None,
        target_id: Optional[str] = None,
        extrude: Optional[bool] = None,
        tessellate: Optional[bool] = None,
        altitude_mode: Optional[AltitudeMode] = None,
        geometry: Optional[geo.LineString] = None,
        kml_coordinates: Optional[Coordinates] = None,
        **kwargs: Any,
    ) -> None:
        if geometry is not None and kml_coordinates is not None:
            raise ValueError("geometry and kml_coordinates are mutually exclusive")
        if kml_coordinates is None:
            kml_coordinates = Coordinates(coords=geometry.coords) if geometry else None
        self.kml_coordinates = kml_coordinates
        super().__init__(
            ns=ns,
            name_spaces=name_spaces,
            id=id,
            target_id=target_id,
            extrude=extrude,
            tessellate=tessellate,
            altitude_mode=altitude_mode,
            # geometry=geometry,
            **kwargs,
        )

    def __repr__(self) -> str:
        """Create a string (c)representation for LineString."""
        return (
            f"{self.__class__.__module__}.{self.__class__.__name__}("
            f"ns={self.ns!r}, "
            f"name_spaces={self.name_spaces!r}, "
            f"id={self.id!r}, "
            f"target_id={self.target_id!r}, "
            f"extrude={self.extrude!r}, "
            f"tessellate={self.tessellate!r}, "
            f"altitude_mode={self.altitude_mode}, "
            f"geometry={self.geometry!r}, "
            f"**kwargs={self._get_splat()!r},"
            ")"
        )

    def __bool__(self) -> bool:
        return bool(self.kml_coordinates)

    @property
    def geometry(self) -> Optional[geo.LineString]:
        if not self.kml_coordinates:
            return None
        return geo.LineString.from_coordinates(self.kml_coordinates.coords)


registry.register(
    LineString,
    item=RegistryItem(
        classes=(Coordinates,),
        attr_name="kml_coordinates",
        node_name="coordinates",
        get_kwarg=xml_subelement_kwarg,
        set_element=xml_subelement,
    ),
)


class LinearRing(LineString):
    def __init__(
        self,
        *,
        ns: Optional[str] = None,
        name_spaces: Optional[Dict[str, str]] = None,
        id: Optional[str] = None,
        target_id: Optional[str] = None,
        extrude: Optional[bool] = None,
        tessellate: Optional[bool] = None,
        altitude_mode: Optional[AltitudeMode] = None,
        geometry: Optional[geo.LinearRing] = None,
        kml_coordinates: Optional[Coordinates] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            ns=ns,
            name_spaces=name_spaces,
            id=id,
            target_id=target_id,
            extrude=extrude,
            tessellate=tessellate,
            altitude_mode=altitude_mode,
            geometry=geometry,
            kml_coordinates=kml_coordinates,
            **kwargs,
        )

    def __repr__(self) -> str:
        """Create a string (c)representation for LinearRing."""
        return (
            f"{self.__class__.__module__}.{self.__class__.__name__}("
            f"ns={self.ns!r}, "
            f"name_spaces={self.name_spaces!r}, "
            f"id={self.id!r}, "
            f"target_id={self.target_id!r}, "
            f"extrude={self.extrude!r}, "
            f"tessellate={self.tessellate!r}, "
            f"altitude_mode={self.altitude_mode}, "
            f"geometry={self.geometry!r}, "
            f"**kwargs={self._get_splat()!r},"
            ")"
        )

    @property
    def geometry(self) -> Optional[geo.LineString]:
        if not self.kml_coordinates:
            return None
        return geo.LinearRing.from_coordinates(self.kml_coordinates.coords)

    @classmethod
    def _get_geometry(
        cls,
        *,
        ns: str,
        element: Element,
        strict: bool,
    ) -> Optional[geo.LinearRing]:
        coords = cls._get_coordinates(ns=ns, element=element, strict=strict)
        try:
            return cast(geo.LinearRing, geo.LinearRing.from_coordinates(coords))
        except (IndexError, TypeError, DimensionError) as e:
            handle_invalid_geometry_error(
                error=e,
                element=element,
                strict=strict,
            )
        return None


class Polygon(_Geometry):
    def __init__(
        self,
        *,
        ns: Optional[str] = None,
        name_spaces: Optional[Dict[str, str]] = None,
        id: Optional[str] = None,
        target_id: Optional[str] = None,
        extrude: Optional[bool] = None,
        tessellate: Optional[bool] = None,
        altitude_mode: Optional[AltitudeMode] = None,
        geometry: geo.Polygon,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            ns=ns,
            name_spaces=name_spaces,
            id=id,
            target_id=target_id,
            extrude=extrude,
            tessellate=tessellate,
            altitude_mode=altitude_mode,
            geometry=geometry,
            **kwargs,
        )

    def __repr__(self) -> str:
        """Create a string (c)representation for Polygon."""
        return (
            f"{self.__class__.__module__}.{self.__class__.__name__}("
            f"ns={self.ns!r}, "
            f"name_spaces={self.name_spaces!r}, "
            f"id={self.id!r}, "
            f"target_id={self.target_id!r}, "
            f"extrude={self.extrude!r}, "
            f"tessellate={self.tessellate!r}, "
            f"altitude_mode={self.altitude_mode}, "
            f"geometry={self.geometry!r}, "
            f"**kwargs={self._get_splat()!r},"
            ")"
        )

    def etree_element(
        self,
        precision: Optional[int] = None,
        verbosity: Verbosity = Verbosity.normal,
    ) -> Element:
        element = super().etree_element(precision=precision, verbosity=verbosity)
        if not self.geometry:
            return element
        assert isinstance(self.geometry, geo.Polygon)
        linear_ring = partial(LinearRing, ns=self.ns, extrude=None, tessellate=None)
        outer_boundary = cast(
            Element,
            config.etree.SubElement(  # type: ignore[attr-defined]
                element,
                f"{self.ns}outerBoundaryIs",
            ),
        )
        outer_boundary.append(
            linear_ring(geometry=self.geometry.exterior).etree_element(
                precision=precision,
                verbosity=verbosity,
            ),
        )
        for interior in self.geometry.interiors:
            inner_boundary = cast(
                Element,
                config.etree.SubElement(  # type: ignore[attr-defined]
                    element,
                    f"{self.ns}innerBoundaryIs",
                ),
            )
            inner_boundary.append(
                linear_ring(geometry=interior).etree_element(
                    precision=precision,
                    verbosity=verbosity,
                ),
            )
        return element

    @classmethod
    def _get_geometry(
        cls,
        *,
        ns: str,
        element: Element,
        strict: bool,
    ) -> Optional[geo.Polygon]:
        outer_boundary = element.find(f"{ns}outerBoundaryIs")
        if outer_boundary is None:
            error = config.etree.tostring(  # type: ignore[attr-defined]
                element,
                encoding="UTF-8",
            ).decode(
                "UTF-8",
            )
            msg = f"Missing outerBoundaryIs in {error}"
            raise KMLParseError(msg)
        outer_ring = outer_boundary.find(f"{ns}LinearRing")
        if outer_ring is None:
            error = config.etree.tostring(  # type: ignore[attr-defined]
                element,
                encoding="UTF-8",
            ).decode(
                "UTF-8",
            )
            msg = f"Missing LinearRing in {error}"
            raise KMLParseError(msg)
        exterior = LinearRing._get_geometry(ns=ns, element=outer_ring, strict=strict)
        interiors = []
        for inner_boundary in element.findall(f"{ns}innerBoundaryIs"):
            inner_ring = inner_boundary.find(f"{ns}LinearRing")
            if inner_ring is None:
                error = config.etree.tostring(  # type: ignore[attr-defined]
                    element,
                    encoding="UTF-8",
                ).decode(
                    "UTF-8",
                )
                msg = f"Missing LinearRing in {error}"
                raise KMLParseError(msg)
            if hole := LinearRing._get_geometry(
                ns=ns,
                element=inner_ring,
                strict=strict,
            ):
                interiors.append(hole)
        if exterior:
            return geo.Polygon.from_linear_rings(exterior, *interiors)
        return None


def create_multigeometry(
    geometries: Sequence[AnyGeometryType],
) -> Optional[MultiGeometryType]:
    """
    Create a MultiGeometry from a sequence of geometries.

    Args:
    ----
        geometries: Sequence of geometries.

    Returns:
    -------
        MultiGeometry

    """
    geom_types = {geom.geom_type for geom in geometries}
    if not geom_types:
        return None
    if len(geom_types) == 1:
        geom_type = geom_types.pop()
        map_to_geometries = {
            geo.Point.__name__: geo.MultiPoint.from_points,
            geo.LineString.__name__: geo.MultiLineString.from_linestrings,
            geo.Polygon.__name__: geo.MultiPolygon.from_polygons,
        }
        for geometry_name, constructor in map_to_geometries.items():
            if geom_type == geometry_name:
                return constructor(  # type: ignore[operator, no-any-return]
                    *geometries,
                )

    return geo.GeometryCollection(geometries)


class MultiGeometry(_Geometry):
    map_to_kml = {
        geo.Point: Point,
        geo.LineString: LineString,
        geo.Polygon: Polygon,
        geo.LinearRing: LinearRing,
    }
    multi_geometries = (
        geo.MultiPoint,
        geo.MultiLineString,
        geo.MultiPolygon,
        geo.GeometryCollection,
    )

    def __init__(
        self,
        *,
        ns: Optional[str] = None,
        name_spaces: Optional[Dict[str, str]] = None,
        id: Optional[str] = None,
        target_id: Optional[str] = None,
        extrude: Optional[bool] = None,
        tessellate: Optional[bool] = None,
        altitude_mode: Optional[AltitudeMode] = None,
        geometry: MultiGeometryType,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            ns=ns,
            name_spaces=name_spaces,
            id=id,
            target_id=target_id,
            extrude=extrude,
            tessellate=tessellate,
            altitude_mode=altitude_mode,
            geometry=geometry,
            **kwargs,
        )

    def __repr__(self) -> str:
        """Create a string (c)representation for MultiGeometry."""
        return (
            f"{self.__class__.__module__}.{self.__class__.__name__}("
            f"ns={self.ns!r}, "
            f"name_spaces={self.name_spaces!r}, "
            f"id={self.id!r}, "
            f"target_id={self.target_id!r}, "
            f"extrude={self.extrude!r}, "
            f"tessellate={self.tessellate!r}, "
            f"altitude_mode={self.altitude_mode}, "
            f"geometry={self.geometry!r}, "
            f"**kwargs={self._get_splat()!r},"
            ")"
        )

    def etree_element(
        self,
        precision: Optional[int] = None,
        verbosity: Verbosity = Verbosity.normal,
    ) -> Element:
        element = super().etree_element(precision=precision, verbosity=verbosity)
        _map_to_kml = {mg: self.__class__ for mg in self.multi_geometries}
        _map_to_kml.update(self.map_to_kml)
        if self.geometry is None:
            return element
        assert isinstance(self.geometry, self.multi_geometries)
        for geometry in self.geometry.geoms:
            geometry_class = _map_to_kml[type(geometry)]
            element.append(
                geometry_class(
                    ns=self.ns,
                    name_spaces=self.name_spaces,
                    extrude=None,
                    tessellate=None,
                    altitude_mode=None,
                    geometry=geometry,  # type: ignore[arg-type]
                ).etree_element(precision=precision, verbosity=verbosity),
            )
        return element

    @classmethod
    def _get_geometry(
        cls,
        *,
        ns: str,
        element: Element,
        strict: bool,
    ) -> Optional[MultiGeometryType]:
        geometries = []
        allowed_geometries = (cls, *tuple(cls.map_to_kml.values()))
        for g in allowed_geometries:
            for e in element.findall(f"{ns}{g.__name__}"):
                geometry = g._get_geometry(  # type: ignore[attr-defined]
                    ns=ns,
                    element=e,
                    strict=strict,
                )
                if geometry is not None:
                    geometries.append(geometry)
        return create_multigeometry(geometries)


def create_kml_geometry(
    geometry: Union[GeoType, GeoCollectionType],
    *,
    ns: Optional[str] = None,
    name_spaces: Optional[Dict[str, str]] = None,
    id: Optional[str] = None,
    target_id: Optional[str] = None,
    extrude: Optional[bool] = None,
    tessellate: Optional[bool] = None,
    altitude_mode: Optional[AltitudeMode] = None,
) -> _Geometry:
    """
    Create a KML geometry from a geometry object.

    Args:
    ----
        geometry: Geometry object.
        ns: Namespace of the object
        id: Id of the object
        target_id: Target id of the object
        extrude: Specifies whether to connect the feature to the ground with a line.
        tessellate: Specifies whether to allow the LineString to follow the terrain.
        altitude_mode: Specifies how altitude components in the <coordinates>
                       element are interpreted.

    Returns:
    -------
        KML geometry object.

    """
    _map_to_kml = {
        geo.Point: Point,
        geo.Polygon: Polygon,
        geo.LinearRing: LinearRing,
        geo.LineString: LineString,
        geo.MultiPoint: MultiGeometry,
        geo.MultiLineString: MultiGeometry,
        geo.MultiPolygon: MultiGeometry,
        geo.GeometryCollection: MultiGeometry,
    }
    geom = shape(geometry)
    for geometry_class, kml_class in _map_to_kml.items():
        if isinstance(geom, geometry_class):
            return cast(
                _Geometry,
                kml_class(
                    ns=ns,
                    name_spaces=name_spaces,
                    id=id,
                    target_id=target_id,
                    extrude=extrude,
                    tessellate=tessellate,
                    altitude_mode=altitude_mode,
                    geometry=geom,
                ),
            )
    # this should be unreachable, but mypy doesn't know that
    msg = f"Unsupported geometry type {type(geometry)}"  # pragma: no cover
    raise KMLWriteError(msg)  # pragma: no cover
