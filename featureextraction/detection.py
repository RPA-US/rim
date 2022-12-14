import json
import numpy as np
import keras_ocr
import cv2
import pandas as pd
import matplotlib.pyplot as plt
from os.path import join as pjoin
import os
import featureextraction.utils as utils
import os
import cv2
import pandas as pd
import numpy as np
from rim.settings import cropping_threshold, platform_name, detection_phase_name
from art import tprint
import pickle
from tqdm import tqdm
from featureextraction.gaze_analysis import gaze_events_associated_to_event_time_range

"""
Text boxes detection: KERAS_OCR

In order to detect the text boxes inside the screenshots, we define the get_keras_ocr_image.
This function has a list of images as input, and a list of lists with the coordinates of text boxes coordinates
"""

def get_ocr_image(pipeline, param_img_root, images_input):
    """
    Applies Keras-OCR over the input image or images to extract plain text and the coordinates corresponding
    to the present words

    :param pipeline: keras pipeline
    :type pipeline: keras pipeline
    :param param_img_root: Path where the imaages associated to each log row are stored
    :type param_img_root: str
    :param images_input: Path or list of paths of the image/s to process
    :type images_input: str or list
    :returns: List of lists corresponding the words identified in the input. Example: ('delete', array([[1161.25,  390.  ], [1216.25,  390.  ], [1216.25,  408.75], [1161.25,  408.75]], dtype=float32))
    :rtype: list
    """

    if not isinstance(images_input, list):
        # print("Solamente una imagen como entrada")
        images_input = [images_input]

    # Get a set of three example images
    images = [
        keras_ocr.tools.read(param_img_root + path) for path in images_input
    ]
    # Each list of predictions in prediction_groups is a list of
    # (word, box) tuples.
    prediction_groups = pipeline.recognize(images)
    # Plot the predictions
    # fig, axs = plt.subplots(nrows=len(images), figsize=(20, 20))
    # for ax, image, predictions in zip(axs, images, prediction_groups):
    #     keras_ocr.tools.drawAnnotations(image=image, predictions=predictions, ax=ax)
    return prediction_groups


def nesting_inspection(org, grey, compos, ffl_block):
    '''
    Inspect all big compos through block division by flood-fill
    :param ffl_block: gradient threshold for flood-fill
    :return: nesting compos
    '''
    nesting_compos = []
    for i, compo in enumerate(compos):
        if compo.height > 50:
            replace = False
            clip_grey = compo.compo_clipping(grey)
            n_compos = utils.nested_components_detection(
                clip_grey, org, grad_thresh=ffl_block, show=False)

            for comp in n_compos:
                comp.compo_relative_position(
                    compo.bbox.col_min, compo.bbox.row_min)

            for n_compo in n_compos:
                if n_compo.redundant:
                    compos[i] = n_compo
                    replace = True
                    break
            if not replace:
                nesting_compos += n_compos
    return nesting_compos


def get_uied_gui_components_crops(input_imgs_path, image_names, img_index):
    '''
    Analyzes an image and extracts its UI components with an alternative algorithm type

    :param param_img_root: Path to the image
    :type param_img_root: str
    :param image_names: Names of the images in the path
    :type image_names: list
    :param img_index: Index of the image we want to analyze in images_names
    :type img_index: int
    :return: List of image crops and Dict object with components detected
    :rtype: Tuple
    '''
    resize_by_height = 800
    input_img_path = pjoin(input_imgs_path, image_names[img_index])

    '''
    ele:min-grad: gradient threshold to produce binary map         
    ele:ffl-block: fill-flood threshold
    ele:min-ele-area: minimum area for selected elements 
    ele:merge-contained-ele: if True, merge elements contained in others
    text:max-word-inline-gap: words with smaller distance than the gap are counted as a line
    text:max-line-gap: lines with smaller distance than the gap are counted as a paragraph

    Tips:
    1. Larger *min-grad* produces fine-grained binary-map while prone to over-segment element to small pieces
    2. Smaller *min-ele-area* leaves tiny elements while prone to produce noises
    3. If not *merge-contained-ele*, the elements inside others will be recognized, while prone to produce noises
    4. The *max-word-inline-gap* and *max-line-gap* should be dependent on the input image size and resolution
    '''
    uied_params = {
        'min-grad': 3,
        'ffl-block': 5,
        'min-ele-area': 25,
        'merge-contained-ele': True,
        'max-word-inline-gap': 4,
        'max-line-gap': 4
    }

    # ##########################
    # COMPONENT DETECTION
    # ##########################

    # *** Step 1 *** pre-processing: read img -> get binary map
    org, grey = utils.read_img(input_img_path, resize_by_height)
    binary = utils.binarization(org, grad_min=int(uied_params['min-grad']))

    # *** Step 2 *** element detection
    utils.rm_line(binary, show=False, wait_key=0)
    uicompos = utils.component_detection(
        binary, min_obj_area=int(uied_params['min-ele-area']))

    # *** Step 3 *** results refinement
    uicompos = utils.compo_filter(uicompos, min_area=int(
        uied_params['min-ele-area']), img_shape=binary.shape)
    uicompos = utils.merge_intersected_compos(uicompos)
    utils.compo_block_recognition(binary, uicompos)
    if uied_params['merge-contained-ele']:
        uicompos = utils.rm_contained_compos_not_in_block(uicompos)
    utils.compos_update(uicompos, org.shape)
    utils.compos_containment(uicompos)

    # *** Step 4 ** nesting inspection: check if big compos have nesting element
    uicompos += nesting_inspection(org, grey,
                                   uicompos, ffl_block=uied_params['ffl-block'])
    utils.compos_update(uicompos, org.shape)

    # ##########################
    # RESULTS
    # ##########################

    # *** Step 5 *** save detection result
    utils.compos_update(uicompos, org.shape)

    clips = [compo.compo_clipping(org) for compo in uicompos]

    return clips, uicompos


def get_gui_components_crops(param_img_root, image_names, texto_detectado_ocr, path_to_save_bordered_images, add_words_columns, img_index):
    '''
    Analyzes an image and extracts its UI components

    :param param_img_root: Path to the image
    :type param_img_root: str
    :param image_names: Names of the images in the path
    :type image_names: list
    :param texto_detectado_ocr: Text detected by OCR in previous step
    :type texto_detectado_ocr: list
    :param path_to_save_bordered_images: Path to save the image along with the components detected
    :type path_to_save_bordered_images: str
    :param add_words_columns: Save words detected by OCR
    :type add_words_columns: bool
    :param img_index: Index of the image we want to analyze in images_names
    :type img_index: int
    :return: Crops and text inside components
    :rtype: Tuple
    '''
    words = {}
    words_columns_names = {}

    image_path = param_img_root + image_names[img_index]
    # Read the image
    img = cv2.imread(image_path)
    img_copy = img.copy()
    # cv2_imshow(img_copy)

    # Store on global_y all the "y" coordinates and text boxes
    # Each row is a different text box, much more friendly than the format returned by keras_ocr 
    global_y = []
    global_x = []
    words[img_index] = {}

    for j in range(0, len(texto_detectado_ocr[img_index])):
        coordenada_y = []
        coordenada_x = []

        for i in range(0, len(texto_detectado_ocr[img_index][j][1])):
            coordenada_y.append(texto_detectado_ocr[img_index][j][1][i][1])
            coordenada_x.append(texto_detectado_ocr[img_index][j][1][i][0])

        if add_words_columns:
            word = texto_detectado_ocr[img_index][j][0]
            centroid = (np.mean(coordenada_x), np.mean(coordenada_y))
            if word in words[img_index]:
                words[img_index][word] += [centroid]
            else:
                words[img_index][word] = [centroid]

            if word in words_columns_names:
                words_columns_names[word] += 1
            else:
                words_columns_names[word] = 1

        global_y.append(coordenada_y)
        global_x.append(coordenada_x)
        # print('Coord y, cuadro texto ' +str(j+1)+ str(global_y[j]))
        # print('Coord x, cuadro texto ' +str(j+1)+ str(global_x[j]))

    # print("Number of text boxes detected (iteration " + str(img_index) + "): " + str(len(texto_detectado_ocr[img_index])))

    # Interval calculation of the text boxes
    intervalo_y = []
    intervalo_x = []
    for j in range(0, len(global_y)):
        intervalo_y.append([int(max(global_y[j])), int(min(global_y[j]))])
        intervalo_x.append([int(max(global_x[j])), int(min(global_x[j]))])
    # print("Intervalo y", intervalo_y)
    # print("Intervalo x", intervalo_x)

    # Conversion to grey Scale
    gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # cv2_imshow(gris)

    # Gaussian blur
    gauss = cv2.GaussianBlur(gris, (5, 5), 0)
    # cv2_imshow(gauss)

    # Border detection with Canny
    canny = cv2.Canny(gauss, 50, 150)
    # cv2_imshow(canny)

    # Countour search in the image
    (contornos, _) = cv2.findContours(canny.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    # print("Number of GUI components detected: ", len(contornos), "\n")

    # draw the countours on the image
    cv2.drawContours(img_copy, contornos, -1, (0, 0, 255), 2)
    # cv2_imshow(img_copy)
    cv2.imwrite(path_to_save_bordered_images + image_names[img_index] + '_bordered.png', img_copy)

    # We carry out the crops for each detected countour
    recortes = []
    lista_para_no_recortar_dos_veces_mismo_gui = []

    text_or_not_text = []

    comp_json = {"img_shape": [img.shape], "compos": []}

    for j in range(0, len(contornos)):
        cont_horizontal = []
        cont_vertical = []
        # Obtain x and y max and min values of the countour
        for i in range(0, len(contornos[j])):
            cont_horizontal.append(contornos[j][i][0][0])
            cont_vertical.append(contornos[j][i][0][1])
        x = min(cont_horizontal)
        w = max(cont_horizontal)
        y = min(cont_vertical)
        h = max(cont_vertical)
        #print('Coord x, componente' + str(j+1) + '  ' + str(x) + ' : ' + str(w))
        #print('Coord y, componente' + str(j+1) + '  ' + str(y) + ' : ' + str(h))

        # Check that the countours are not overlapping with text boxes. If so, cut the text boxes
        condicion_recorte = True
        no_solapa = 1
        for k in range(0, len(intervalo_y)):
            solapa_y = 0
            solapa_x = 0
            y_min = min(intervalo_y[k])-cropping_threshold
            y_max = max(intervalo_y[k])+cropping_threshold
            x_min = min(intervalo_x[k])-cropping_threshold
            x_max = max(intervalo_x[k])+cropping_threshold
            # and max([y-y_min, y_max-y, h-y_min, y_max-h])<=surrounding_max_diff
            solapa_y = (y_min <= y <= y_max) or (y_min <= h <= y_max)
            # and max([x-x_min, x_max-x, w-x_min, x_max-w])<=surrounding_max_diff
            solapa_x = (x_min <= x <= x_max) or (x_min <= w <= x_max)
            if (solapa_y and solapa_x):
                if (lista_para_no_recortar_dos_veces_mismo_gui.count(k) == 0):
                    lista_para_no_recortar_dos_veces_mismo_gui.append(k)
                else:
                    # print("Text inside GUI component " + str(k) + " twice")
                    condicion_recorte = False
                x = min(intervalo_x[k])
                w = max(intervalo_x[k])
                y = min(intervalo_y[k])
                h = max(intervalo_y[k])
                no_solapa *= 0
                #crop_img = img[min(intervalo_y[k]) : max(intervalo_y[k]), min(intervalo_x[k]) : max(intervalo_x[k])]
                #print("Componente " + str(j+1) + " solapa con cuadro de texto")
        # if (solapa_y == 1 and solapa_x == 1):
        #crop_img = img[min(intervalo_y[k]) : max(intervalo_y[k]), min(intervalo_x[k]) : max(intervalo_x[k])]
        #print("Componente " + str(j+1) + " solapa con cuadro de texto")
        # recortes.append(crop_img)
        # else:
        # If the GUI component overlaps with the textbox, cut the later one
        # gaze_point_x and gaze_point_x >= x and gaze_point_x <= w and gaze_point_y >= y and gaze_point_y <= h and duration >= gaze_analysis_threshold
        coincidence_with_attention_point = True
        if (condicion_recorte and coincidence_with_attention_point):
            crop_img = img[y:h, x:w]
            text = [word for word in words[img_index] if len([coord for coord in words[img_index][word] if x <= coord[0] <= w and y <= coord[1] <= h]) > 0]
            is_text = True if len(text)>0 else False
            comp_json["compos"].append({
                "id": int(j+1),
                "class": "Text" if is_text else "Compo",
                "Text": text[0] if is_text else None,
                "column_min": int(x),
                "row_min": int(y),
                "column_max": int(w),
                "row_max": int(h),
                "width": int(w - x),
                "height": int(h - y)
            })
            recortes.append(crop_img)
            text_or_not_text.append(abs(no_solapa-1))

    return (recortes, comp_json, text_or_not_text, words)

def detect_images_components(param_img_root, log, special_colnames, skip, image_names, text_detected_by_OCR, path_to_save_bordered_images, add_words_columns, algorithm):
    """
    With this function we process the screencaptures using the information resulting by aplying OCR
    and the image itself. We crop the GUI components and store them in a numpy array with all the 
    cropped components for each of the images in images_names


    :param param_img_root: Path where the imaages associated to each log row are stored
    :type param_img_root: str
    :image_names: Names of images in the log by alphabetical order
    :type image_names: list
    :texto_detectado_ocr: List of lists corresponding the words identified in the images on the log file
    :type texto_detectado_ocr: list
    :path_to_save_bordered_images: Path where the images along with their component borders must be stored
    :type path_to_save_bordered_images: str
    """
    path_to_save_gui_components_npy = param_img_root+"components_npy/"
    path_to_save_components_json = param_img_root+"components_json/"

    # Iterate over the list of images
    for img_index in tqdm(range(0, len(image_names)), desc=f"Getting crops for {param_img_root}"):
        screenshot_texts_npy = path_to_save_gui_components_npy + image_names[img_index] + "_texts.npy"
        screenshot_npy = path_to_save_gui_components_npy + image_names[img_index] + ".npy"
        exists_screenshot_npy = os.path.exists(screenshot_npy)

        screenshot_json = path_to_save_components_json + image_names[img_index] + ".json"
        exists_screenshot_json = os.path.exists(screenshot_json)
        
        overwrite = (not exists_screenshot_json) or (not exists_screenshot_npy) or (not skip)

        # Gaze analysis?

        if overwrite:

            if algorithm == "rpa-us":
                recortes, comp_json, text_or_not_text, words = get_gui_components_crops(param_img_root, image_names, text_detected_by_OCR, path_to_save_bordered_images, add_words_columns, img_index)
                
                # save metadata json
                with open(path_to_save_components_json + image_names[img_index] + '.json', "w") as outfile:
                    json.dump(comp_json, outfile)

                # save ui elements npy
                aux = np.array(recortes)
                np.save(screenshot_npy, aux)

                # save texts npy
                np.save(screenshot_texts_npy, text_or_not_text)

            elif algorithm == "uied":
                # this method edit the metadata json with the ui element class and text if corresponds 
                recortes, uicompos = get_uied_gui_components_crops(param_img_root, image_names, img_index)

                # store all bounding boxes from the ui elements that are in 'uicompos'
                utils.save_corners_json(path_to_save_components_json + image_names[img_index] + '.json', uicompos)

                # save ui elements npy
                aux = np.array(recortes, dtype=object)
                np.save(screenshot_npy, aux)

            # if (add_words_columns and (not no_modification)) or (add_words_columns and (not os.path.exists(param_img_root+"text_colums.csv"))):
            #     storage_text_info_as_dataset(words, image_names, log, param_img_root)


# def storage_text_info_as_dataset(words, image_names, log, param_img_root):
#     headers = []
#     for w in words[1]:
#         if words[1][w] == 1:
#             headers.append(w)
#         else:
#             [headers.append(w+"_"+str(i)) for i in range(1, words[1][w]+1)]
#     initial_row = ["NaN"]*len(headers)

#     df = pd.DataFrame([], columns=headers)
#     words = words[0]

#     for j in range(0, len(image_names)):
#         for w in words[j]:
#             centroid_ls = list(words[j][w])
#             if len(centroid_ls) == 1:
#                 if w in headers:
#                     pos = headers.index(w)
#                 else:
#                     pos = headers.index(w+"_1")
#                     initial_row[pos] = centroid_ls[0]
#             else:
#                 ac = 0
#                 for index, h in enumerate(headers):
#                     if len(centroid_ls) > ac and (str(w) in h):
#                         initial_row[index] = centroid_ls[ac]
#                         ac += 1
#         df.loc[j] = initial_row

#     log_enriched = log.join(df).fillna(method='ffill')
#     log_enriched.to_csv(param_img_root+"text_colums.csv")


"""
GUI component detection

The objective of this section is to be able to detect, define and crop each
of the graphic components (Symbols, images or text boxes) that form constitute
a screenshot

Libraries Import: We will use mainly keras_ocr and Opencv (Cv2).
=====================================
Border detection and cropping: OpenCV

We make use of OpenCV to carry out the following tasks:
- Image read.
- Calculation of intervals occupied by the text boxes obtained from keras_ocr
- Image processing:
    > GreyScale conversion
    > Gaussian blur
    > **Canny algorithm** for border detection
    > Countour detection
- Comparison betweeen countour and text boxes, giving more importance to text boxes 
    in case there is overlapping
- Final crop of each of the components

"""


def ui_elements_detection(param_log_path, param_img_root, special_colnames, add_words_columns=False, skip=False, algorithm="legacy"):
    tprint(platform_name + " - " + detection_phase_name, "fancy60")
    print(param_img_root+"\n")
    
    # Log read
    log = pd.read_csv(param_log_path, sep=",")
    # Extract the names of the screenshots associated to each of the rows in the log
    image_names = log.loc[:, special_colnames["Screenshot"]].values.tolist()
    pipeline = keras_ocr.pipeline.Pipeline()
    file_exists = os.path.exists(param_img_root + "images_ocr_info.txt")

    if file_exists:
        print("\n\nReading images OCR info from file...")
        with open(param_img_root + "images_ocr_info.txt", "rb") as fp:   # Unpickling
            text_corners = pickle.load(fp)
    else:
        text_corners = []
        for img in image_names:
            ocr_result = get_ocr_image(pipeline, param_img_root, img)
            text_corners.append(ocr_result[0])
        with open(param_img_root + "images_ocr_info.txt", "wb") as fp:  # Pickling
            pickle.dump(text_corners, fp)

    # print(len(text_corners))

    bordered = param_img_root+"contours/"
    components_npy = param_img_root+"components_npy/"
    components_json = param_img_root+"components_json/"
    for p in [bordered, components_npy, components_json]:
        if not os.path.exists(p):
            os.mkdir(p)

    detect_images_components(param_img_root, log, special_colnames, skip, image_names, text_corners, bordered, add_words_columns, algorithm)



############################################
############# Development utils ############
############################################

def check_npy_components_of_capture(image_name="1.png.npy", image_path="media/screenshots/components_npy/", interactive=False):
    if interactive:
        image_path = input("Enter path to images numpy arrays location: ")
        image_name = input("Enter numpy array file name: ")
    recortes = np.load(image_path+image_name, allow_pickle=True)
    for i in range(0, len(recortes)):
        print("Length: " + str(len(recortes)))
        if recortes[i].any():
            print("\nComponent: ", i+1)
            plt.imshow(recortes[i], interpolation='nearest')
            plt.show()
        else:
            print("Empty component")
    if interactive:
        image_path = input(
            "Do you want to check another image components? Indicate another npy file name: ")
        check_npy_components_of_capture(image_path, None, True)