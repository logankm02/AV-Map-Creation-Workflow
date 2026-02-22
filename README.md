# AV Map Creation Workflow for Autonomous Vehicle Simulations

This repository outlines a simulator-agnostic workflow to create maps for Autonomous Vehicle (AV) simulation testing. It enables the generation of:

- **3D Mesh Models**
- **Point Cloud Data (PCD)**
- **Lanelet2 Maps**

These outputs are compatible with **Autoware** and **AWSIM**, facilitating both virtual AV testing and future real-world deployment. The workflow was designed to address the lack of easily reproducible, parking-lot-sized maps for AVP (Autonomous Valet Parking) research.

Demonstrations have been provided below for each part. This [Google Drive](https://drive.google.com/drive/folders/1Mtkr13VCS5KdGLns7JRVTOxwJmy0Xnit?usp=drive_link) also contains all the demonstrations.

---

## Table of Contents

- [Motivation](#motivation)
- [Architecture](#architecture)
- [Setup](#setup)
  - [Step 1: Clone the Repository and Set Up the Project Structure](#step-1-clone-the-repository-and-set-up-the-project-structure)
  - [Step 2: Download the OSM File](#step-2-download-the-osm-file)
  - [Step 3: Generate OBJ Files and PCD Files](#step-3-generate-obj-files-and-pcd-files)
  - [Step 4: Auto-Generate Lanelet2 Map](#step-4-auto-generate-lanelet2-map)
  - [Step 5: Refine in Vector Map Builder](#step-5-refine-in-vector-map-builder)
  - [Step 6: Nullify Latitude/Longitude](#step-6-nullify-latitudelongitude)
  - [Step 7: Import Files to Autoware](#step-7-import-files-to-autoware)
  - [Step 8: Import to AWSIM](#step-8-import-to-awsim)
- [Results](#results)
- [Localization Instability](#localization-instability)
- [Limitations](#limitations)
- [Troubleshooting](#troubleshooting)
- [Publication and Recognition](#publication-and-recognition)

---

## Motivation

At the time of this project's development, AWSIM and Autoware only included a single city-scale map, which lacked critical low-speed elements like parking lots. Moreover, existing documentation for map creation was often outdated or platform-dependent (e.g., CARLA, LGSVL).

To address this:
- Created a **custom parking lot map** of Ontario Tech University's SIRC campus.
- Designed a **lightweight workflow** that avoids heavy simulation dependencies like CARLA.
- Used **open-source, low-resource tools** to make the pipeline accessible.

## Architecture
<img width="1193" height="466" alt="image" src="https://github.com/user-attachments/assets/bcb7f795-1a03-4ee7-ae2c-b146f9da0849" />

---

## Setup

### Step 1: Clone the Repository and Set Up the Project Structure
```bash
cd ~/
git clone https://github.com/zubxxr/AV-Map-Creation-Workflow
cd AV-Map-Creation-Workflow
mkdir map_files
```

### Step 2: Download the OSM File

[Demonstration](https://drive.google.com/file/d/1siUoWQ66YDEZnNxpCEGZUtRvuZyRF7Ho/view?usp=drive_link)

Use **OpenStreetMap** to export your desired location as an OSM file.

1. Open [OpenStreetMap](https://www.openstreetmap.org/) and search for the location you want to create a map for.

2. Click **Export** in the top header, then select **Manually select a different area** on the left side.

3. Resize the selection area as needed, then click **Export** to download `map.osm`.

4. Copy the file into the project directory:
   ```bash
   cp ~/Downloads/map.osm ~/AV-Map-Creation-Workflow/map_files/
   ```

### Step 3: Generate OBJ Files and PCD Files

This step converts your `.osm` file into a **Point Cloud Data (PCD)** file and a **3D Model** (`.obj`, `.mtl`, and texture files).

1. Navigate to your project workspace:
   ```bash
   cd ~/AV-Map-Creation-Workflow
   ```

2. Create an empty `.pcd` file. This prevents Docker from mistaking the mount path for a folder:
   ```bash
   touch map_files/pointcloud_map.pcd
   ```

3. Pull the Docker container:
   ```bash
   docker pull zubxxr/osm-3d-pcd-pipeline:latest
   ```

4. Run the pipeline:
   ```bash
   docker run --rm -e QT_QPA_PLATFORM=offscreen \
     -v $(pwd)/map_files/map.osm:/app/map.osm \
     -v $(pwd)/map_files/3D_Model:/app/3D_Model \
     -v $(pwd)/map_files/pointcloud_map.pcd:/app/pointcloud_map.pcd \
     zubxxr/osm-3d-pcd-pipeline
   ```

   > **Note for Apple Silicon (M-series) Macs:** The image runs under x86 emulation. If CloudCompare is killed during sampling (OOM), mount a modified `process.sh` with `SAMPLE_MESH DENSITY 10` instead of `100`:
   > ```bash
   > docker run --rm -e QT_QPA_PLATFORM=offscreen \
   >   -v $(pwd)/map_files/map.osm:/app/map.osm \
   >   -v $(pwd)/map_files/3D_Model:/app/3D_Model \
   >   -v $(pwd)/map_files/pointcloud_map.pcd:/app/pointcloud_map.pcd \
   >   -v $(pwd)/process.sh:/app/process.sh \
   >   zubxxr/osm-3d-pcd-pipeline
   > ```
   > Edit `process.sh` and change `DENSITY 100` to `DENSITY 10` before running.

5. Verify the output:
   ```bash
   ls map_files/
   ls map_files/3D_Model/
   ```

   You should see `pointcloud_map.pcd`, and inside `3D_Model/`: `output.obj`, `output.obj.mtl`, and a `textures/` folder.

### Step 4: Auto-Generate Lanelet2 Map

The included `osm_to_lanelet2.py` script converts the OSM road network directly into a Lanelet2-format map, creating lanelets for all highway ways with correct topology (shared boundary nodes at junctions).

```bash
cd ~/AV-Map-Creation-Workflow
python3 osm_to_lanelet2.py map_files/map.osm map_files/raw_lanelet2.osm
```

This produces `map_files/raw_lanelet2.osm` with:
- One lanelet per direction for every road
- Lane widths estimated by road type
- Speed limits from OSM tags
- Shared boundary nodes at intersections for correct routing topology

Also create the map projection info file. Find your MGRS grid zone and 100km square using [this converter](https://legallandconverter.com/p50.html) with any lat/lon from your `map.osm`, then create:

**`map_files/map_projector_info.yaml`**
```yaml
projector_type: MGRS
vertical_datum: WGS84
mgrs_grid: <ZONE><SQUARE>   # e.g. 32TPP
```

### Step 5: Refine in Vector Map Builder

[Demonstration](https://drive.google.com/file/d/1GsgT-V2fWnFuPw8rWdohsYPsOSAnr716/view?usp=drive_link)

Use [Vector Map Builder (VMB)](https://tools.tier4.jp/vector_map_builder_ll2/) to inspect and refine the auto-generated map.

1. Import the PCD as a visual reference: **File > Import PCD > Browse**, select `pointcloud_map.pcd`.

2. Import the auto-generated Lanelet2 map for editing: **File > Import Lanelet2Maps**, select `map_files/raw_lanelet2.osm` along with `map_files/map_projector_info.yaml`.

3. Review and fix the map:
   - Delete lanelets for roads not relevant to your use case (footways, irrelevant streets, etc.)
   - Add parking spaces, stop lines, and any elements not in the OSM data
   - Connect lanelets at intersections where `next lanelet not set` warnings appear
   - Adjust lane widths and boundaries to match the point cloud

   > Make sure the Lanelet2 map is good by exporting it, reimporting it into VMB again, and making sure all the lanelets are correct and not broken. Next, load the map into Autoware PSIM and make sure all areas of the map are routable.

4. Export: **File > Export Lanelet2Maps > OK > Download**

5. Copy the exported file into the project directory:
   ```bash
   cp ~/Downloads/new_lanelet2_maps.osm ~/AV-Map-Creation-Workflow/map_files/
   ```

### Step 6: Nullify Latitude/Longitude

Run the included script to zero out lat/lon coordinates, which prevents infinite map stretching in Autoware:

```bash
cd ~/AV-Map-Creation-Workflow
python3 remove_lat_lon.py map_files/new_lanelet2_maps.osm map_files/lanelet2_map.osm
```

### Step 7: Import Files to Autoware

[Demonstration](https://drive.google.com/file/d/1JRt64q4x_NL__mK30LJ7Vgzp1ZBU6C9e/view?usp=drive_link)

Your `map_files/` directory should now contain:

```
map_files/
├── pointcloud_map.pcd
├── lanelet2_map.osm
└── map_projector_info.yaml
```

Point Autoware to the `map_files/` directory. These files are ready for simulation or real-world integration.

#### Example: Lanelet2 Map and Point Cloud Imported into Autoware
![Importing Files into Autoware](https://github.com/user-attachments/assets/760fefa1-7668-4c97-9531-42e42b6a50a9)

### Step 8: Import to AWSIM

- Import `.obj`, `.mtl`, and `.png` files into the Unity scene by dragging them from the system file manager into the Assets window.
- Drag the `.obj` file into the scene and enable read/write permissions on the mesh.
- Load and align the Lanelet2 file to synchronize with Autoware. [Instructions](https://autowarefoundation.github.io/AWSIM-Labs/main/Components/Environment/LaneletBoundsVisualizer/)

#### Example: Lanelet2 Map and 3D Model Imported into AWSIM
![image](https://github.com/user-attachments/assets/d19eff33-39b4-48cd-9992-01c18400a827)
> Parking lot and vehicles were added in manually.

---

## Results

### Initialization in AWSIM and Autoware
![image](https://github.com/user-attachments/assets/0b7c5f4f-debe-4848-be7e-f8919a99c18b)

### Planning and Navigation
![image](https://github.com/user-attachments/assets/f9b89e0c-2359-4f17-b0ff-eda4dd4d2653)

### Arrival at Parking Spot
![image](https://github.com/user-attachments/assets/f3e45604-2fe0-4f5b-9f1a-c98c1c2fa583)

---

## Localization Instability

In the case of localization instability, the map may need additional features to help localize. This can be done using a 3D mesh editing tool, such as Blender.

The 3D mesh was loaded into Blender after the workflow was used and trimmed to remove unwanted features.

### Raw 3D Mesh
![image](https://github.com/user-attachments/assets/b3e3d646-94dc-447d-96ed-515ec8e7edb4)

### Trimmed 3D Mesh
![image](https://github.com/user-attachments/assets/9616b971-af04-4461-8eb4-871f16bb9b03)

Next, planar, wall-like structures were added around the perimeter of the map to provide additional geometry for LiDAR scan matching.

### Added Perimeter Walls to Enhance LiDAR Scan Matching
<img width="1600" height="766" alt="image" src="https://github.com/user-attachments/assets/1e7680d8-c793-4f7a-93c5-c977cf50ab84" />

The 3D mesh can then be exported again and re-imported into the workflow to generate the PCD file required by Autoware. This simple yet effective adjustment significantly improved localization performance in previously sparse regions of the map.


## Limitations

- **Large OSM maps are not supported:**
  This workflow was designed and tested with relatively small OpenStreetMap (OSM) files. It does not currently scale well to large maps due to memory and processing constraints in the conversion and map-building stages. Attempting to process large `.osm` files may result in performance degradation or failure.

> 📌 _Limitation identified in July 2025._


## Troubleshooting

Feel free to open an **Issue** if there are any problems.

### Entering the Container
To manually enter the container for debugging:
```bash
docker run -e QT_QPA_PLATFORM=offscreen \
  -v $(pwd)/map_files/map.osm:/app/map.osm \
  --entrypoint bash -it zubxxr/osm-3d-pcd-pipeline
```

---


## Publication and Recognition

This repository supports the paper:
> **Zubair Islam**, Ahmaad Ansari, George Daoud, Mohamed El-Darieby
> *A Workflow for Map Creation in Autonomous Vehicle Simulations*
> **GEOProcessing 2025** — Awarded **Best Paper**
> [Read the full paper](https://www.thinkmind.org/library/GEOProcessing/GEOProcessing_2025/geoprocessing_2025_2_40_30041.html)

<p align="left">
  <img src="https://github.com/user-attachments/assets/8dc4020f-a378-4de7-b9d7-facc86c5a187" alt="Best Paper Award – GEOProcessing 2025" width="400"/>
</p>
