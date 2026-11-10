"""
AGS 4.1 Format Handler - Export/Import geotechnical data
AGS (Association of Geotechnical & Geoenvironmental Specialists) Standard Format
"""

from pathlib import Path
from typing import Optional, List
from project_manager import ProjectManager, Project, Borehole, CPTData


class AGS41Handler:
    """Handle AGS 4.1 format export/import"""

    @staticmethod
    def export_project_to_ags(project_name: str, pm: ProjectManager, filepath: str) -> bool:
        """
        Export project with boreholes and CPT data to AGS 4.1 format

        Args:
            project_name: Name of project to export
            pm: ProjectManager instance
            filepath: Path to save .ags file

        Returns:
            True if successful
        """
        project = pm.get_project(project_name)
        if not project:
            return False

        try:
            lines = []

            # Header
            lines.append("*FILE_FSET")
            lines.append('"DATA_FSET"')
            lines.append("*UNIT_SPACING\t1")
            lines.append("*RECORD_DELIMITER\t~")
            lines.append("")

            # PROJECT Group
            lines.append("GROUP,PROJ")
            lines.append("HEADING,PROJ_ID,PROJ_NAM,PROJ_LOC,PROJ_GRD,PROJ_DT")
            lines.append(f"DATA,1,{project.name},{project.location.address},Surface,{project.created_date[:10]}~")
            lines.append("")

            # LOCA Group (Locations - Boreholes)
            boreholes = pm.get_boreholes(project_name)
            if boreholes:
                lines.append("GROUP,LOCA")
                lines.append("HEADING,LOCA_ID,LOCA_NATE,LOCA_NATN,LOCA_TYPE,LOCA_DATM")
                for bh in boreholes:
                    lines.append(f"DATA,{bh.boring_name},{bh.latitude:.4f},{bh.longitude:.4f},Borehole,WGS84~")
                lines.append("")

            # CONE Group (CPT Data)
            cpt_data = pm.get_cpt_data(project_name)
            if cpt_data and boreholes:
                # For now, link CPT data to matching boring name
                for bh in boreholes:
                    if bh.boring_type == "CPT" and cpt_data.boring_name == bh.boring_name:
                        lines.append("GROUP,CONE")
                        lines.append("HEADING,CONE_LOCA,CONE_DPTH,CONE_QCEF,CONE_FSEF,CONE_PUAT")

                        # Add CPT data points
                        for i, depth in enumerate(cpt_data.depth):
                            qc = cpt_data.qc[i] if i < len(cpt_data.qc) else 0
                            fs = cpt_data.fs[i] if i < len(cpt_data.fs) else 0
                            u2 = cpt_data.u2[i] if i < len(cpt_data.u2) else 0
                            lines.append(f"DATA,{bh.boring_name},{depth:.4f},{qc:.4f},{fs:.4f},{u2:.4f}~")
                        lines.append("")

            # Write to file
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))

            return True

        except Exception as e:
            print(f"Error exporting to AGS: {e}")
            return False

    @staticmethod
    def import_boreholes_from_ags(filepath: str, pm: ProjectManager, project_name: str) -> bool:
        """
        Import borehole locations from AGS 4.1 file

        Args:
            filepath: Path to .ags file
            pm: ProjectManager instance
            project_name: Project to import boreholes into

        Returns:
            True if successful
        """
        if not Path(filepath).exists():
            return False

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            # Parse LOCA group for borehole locations
            lines = content.split('\n')
            in_loca_group = False
            in_loca_data = False

            for line in lines:
                line = line.strip()

                if line.startswith("GROUP,LOCA"):
                    in_loca_group = True
                    continue

                if in_loca_group and line.startswith("HEADING"):
                    in_loca_data = True
                    continue

                if in_loca_group and line.startswith("DATA,"):
                    # Parse borehole data
                    parts = line.replace("DATA,", "").replace("~", "").split(',')
                    if len(parts) >= 4:
                        boring_name = parts[0]
                        try:
                            latitude = float(parts[1])
                            longitude = float(parts[2])
                            boring_type = "CPT" if "cone" in line.lower() else "Other"

                            # Add borehole to project
                            bh = Borehole(
                                boring_name=boring_name,
                                latitude=latitude,
                                longitude=longitude,
                                boring_type=boring_type,
                                depth=0.0
                            )
                            pm.add_borehole(project_name, bh)
                        except (ValueError, IndexError):
                            continue

                # Stop at next group
                if in_loca_group and line.startswith("GROUP,") and "LOCA" not in line:
                    break

            return True

        except Exception as e:
            print(f"Error importing from AGS: {e}")
            return False


def format_ags_value(value) -> str:
    """Format a value for AGS 4.1"""
    if isinstance(value, float):
        return f"{value:.4f}"
    elif isinstance(value, int):
        return str(value)
    else:
        return str(value)
