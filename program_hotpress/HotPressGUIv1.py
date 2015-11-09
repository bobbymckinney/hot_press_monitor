#! /usr/bin/python
# -*- coding: utf-8 -*-
"""
Created: 2015-05-29

@author: Bobby McKinney (bobbymckinney@gmail.com)

__Title__ : room temp seebeck
Description:
Comments:
"""
import os
import sys
import wx
from wx.lib.pubsub import pub # For communicating b/w the thread and the GUI
import matplotlib
matplotlib.interactive(False)
matplotlib.use('WXAgg') # The recommended way to use wx with mpl is with WXAgg backend.

from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg
from matplotlib.figure import Figure
from matplotlib.pyplot import gcf, setp
import matplotlib.animation as animation # For plotting
import pylab
import numpy as np
import visa # pyvisa, essential for communicating with the Keithley
from threading import Thread # For threading the processes going on behind the GUI
import time
from datetime import datetime # for getting the current date and time
# Modules for saving logs of exceptions
import minimalmodbus as modbus
import omegacn7500
import exceptions
import sys
from logging_utils import setup_logging_to_file, log_exception
import u6


# for a fancy status bar:
import EnhancedStatusBar as ESB

#==============================================================================
version = '1.0 (2015-10-26)'

modbus.CLOSE_PORT_AFTER_EACH_CALL = True

'''
Global Variables:
'''

# Naming a data file:
dataFile = 'Data.csv'

# placer for directory
filePath = 'global file path'

# placer for files to be created
myfile = 'global file'

APP_EXIT = 1 # id for File\Quit

maxLimit = 70 # Restricts the user to a max temperature

abort_ID = 0 # Abort method

# Global placers for instruments
lj = ''
pid = ''

tc_type = "k-type" # Set the thermocouple type in order to use the correct voltage correction
disp_zero = 0 #Set's the zero point voltage for displacement measurements

# Placers for the GUI plots:

ttemp_sample_list = []
temp_sample_list = []
setpoint_sample_list = []
tdisp_list = []
disp_list = []
tpress_sample_list = []
press_sample_list = []
tpress_chamber_list = []
press_chamber_list = []

#channels for LabJack u6
cyl_pressure_channel = 0
chamber_pressure_channel = 2
left_feedthrough_channel = 6
right_feedthrough_channel = 8
displacement_channel = 4



###############################################################################
class Setup:
    """
    Call this class to run the setup for the Keithley and the PID.
    """
    def __init__(self):
        """
        Prepare the Keithley to take data on the specified channels:
        """
        global lj, pid

        # Define Keithley instrument port:
        lj = LabJack()
        pid = PID('/dev/cu.usbserial', 1)
#end class
###############################################################################

###############################################################################
class PID(omegacn7500.OmegaCN7500):

    #--------------------------------------------------------------------------
    def __init__(self, portname, slaveaddress):
        omegacn7500.OmegaCN7500.__init__(self, portname, slaveaddress)

    #end init

    #--------------------------------------------------------------------------

    # Commands for easy reference:
    #    Use .write_register(command, value) and .read_register(command)
    #    All register values can be found in the Manual or Instruction Sheet.
    #    You must convert each address from Hex to Decimal.
    control = 4101 # Register for control method
    pIDcontrol = 0 # Value for PID control method
    pIDparam = 4124 # Register for PID parameter selection
    pIDparam_Auto = 4 # Value for Auto PID
    tCouple = 4100 # Register for setting the temperature sensor type
    tCouple_K = 0 # K type thermocouple
    heatingCoolingControl = 4102 # Register for Heating/Cooling control selection
    heating = 0 # Value for Heating setting
#end class
###############################################################################

###############################################################################
class LabJack(u6.U6):

    #--------------------------------------------------------------------------
    def __init__(self):
        u6.U6.__init__(self)
    #end init

    #--------------------------------------------------------------------------
    def measure_cyl_pressure(self):
        volts = float(self.getAIN(cyl_pressure_channel, resolutionIndex = 8, gainIndex = 0))
        cyl_press = volts * 10 #PSI
        sample_press = cyl_press * 992845 # Pa

        return cyl_press, sample_press
    #end def

    #--------------------------------------------------------------------------
    def measure_chamber_pressure(self):
        volts = float(self.getAIN(chamber_pressure_channel, resolutionIndex = 8, gainIndex = 0))

        pressure = 10**(volts - 5) #Torr
        return pressure
    #end def

    #--------------------------------------------------------------------------
    def measure_feedthrough_temps(self):
            CJTEMPinC = float(self.getTemperature()) + 2.5 - 273.15

            # The thermocouple's analog voltage
            # Important: Must be in millivolts
            LEFTmVolts = float(self.getAIN(left_feedthrough_channel, resolutionIndex = 8, gainIndex = 3)) * 1000
            RIGHTmVolts = float(self.getAIN(right_feedthrough_channel, resolutionIndex = 8, gainIndex = 3)) * 1000

            LEFTtotalmVolts = LEFTmVolts + tempCToMVolts(CJTEMPinC)
            RIGHTtotalmVolts = RIGHTmVolts + tempCToMVolts(CJTEMPinC)

            LEFT_temp = mVoltsToTempC(LEFTtotalmVolts)
            RIGHT_temp = mVoltsToTempC(RIGHTtotalmVolts)

            return LEFT_temp, RIGHT_temp
    #end def

    #--------------------------------------------------------------------------
    def measure_displacement(self):
        volts = float(self.getAIN(displacement_channel, resolutionIndex = 8, gainIndex = 0))

        disp = 12 * volts + 40  - disp_zero# mm
        return disp
    #end def

    #--------------------------------------------------------------------------
    def zero_displacement(self):
        global disp_zero
        volts = float(self.getAIN(displacement_channel, resolutionIndex = 8, gainIndex = 0))
        disp_zero = 12 * volts + 40 # mm
        print "zero displacement = %f" % (disp_zero)
#end class
###############################################################################

###############################################################################
class ProcessThread(Thread):
    """
    Thread that runs the operations behind the GUI. This includes measuring
    and plotting.
    """

    #--------------------------------------------------------------------------
    def __init__(self):
        """ Init Worker Thread Class """
        Thread.__init__(self)
        self.start()
    #end init

    #--------------------------------------------------------------------------
    def run(self):
        """ Run Worker Thread """
        #Setup()
        td=TakeData()
        #td = TakeDataTest()
    #end def
#end class
###############################################################################

###############################################################################
class TakeData:
    ''' Takes measurements and saves them to file. '''
    #--------------------------------------------------------------------------
    def __init__(self):
        global abort_ID
        global lj, pid

        self.lj = lj
        self.pid = pid

        self.exception_ID = 0

        self.updateGUI(stamp='Status Bar', data='Running')

        self.start = time.time()

        try:
            while abort_ID == 0:

                self.data_measurement()

                self.write_data_to_file()

                #self.safety_check()

                if abort_ID == 1: break
                #end if
            #end while
        #end try

        except exceptions.Exception as e:
            log_exception(e)

            abort_ID = 1

            self.exception_ID = 1

            print "Error Occurred, check error_log.log"
        #end except

        if self.exception_ID == 1:
            self.updateGUI(stamp='Status Bar', data='Exception Occurred')
        #end if
        else:
            self.updateGUI(stamp='Status Bar', data='Finished, Ready')
        #end else

        self.save_files()

        wx.CallAfter(pub.sendMessage, 'Enable Buttons')
    #end init

    #--------------------------------------------------------------------------
    def safety_check(self):
        global maxLimit
        global abort_ID

        if float(self.tempA) > maxLimit or float(self.tempB) > maxLimit:
            abort_ID = 1
    #end def

    #--------------------------------------------------------------------------
    def data_measurement(self):
        # get displacement
        self.disp = self.lj.measure_displacement()
        self.tdisp = time.time() - self.start
        self.updateGUI(stamp="Time Displacement", data=self.tdisp)
        self.updateGUI(stamp="Displacement", data=self.disp)
        print "time: %.0f s\tdisplacement: %f mm" % (self.tdisp, self.disp)

        time.sleep(.1)

        # get cylinder pressure and sample pressure
        self.pressure_cyl, self.pressure_sample = self.lj.measure_cyl_pressure()
        self.tpressure_cyl = time.time() - self.start
        self.tpressure_sample = self.tpressure_cyl
        self.updateGUI(stamp="Time Pressure_Cyl", data=self.tpressure_cyl)
        self.updateGUI(stamp="Pressure_Cyl", data=self.pressure_cyl)
        print "time: %.0f s\tpressure_cylinder: %f PSI" % (self.tpressure_cyl, self.pressure_cyl)
        self.updateGUI(stamp="Time Pressure_Sample", data=self.tpressure_sample)
        self.updateGUI(stamp="Pressure_Sample", data=self.pressure_sample)
        print "time: %.0f s\tpressure_sample: %f MPa" % (self.tpressure_sample, self.pressure_sample * 10**-6)

        time.sleep(.1)

        # get chamber pressure
        self.vacuum = self.lj.measure_chamber_pressure()
        self.tvacuum = time.time() - self.start
        self.updateGUI(stamp="Time Pressure_Chamber", data=self.tvacuum)
        self.updateGUI(stamp="Pressure_Chamber", data=self.vacuum)
        print "time: %.0f s\tpressure_vacuum: %f mTorr" % (self.tvacuum, self.vacuum * 10**3)

        time.sleep(.1)

        # get feedthrough temps
        self.temp_ftl, self.temp_ftr = self.lj.measure_feedthrough_temps()
        self.ttemp_ft = time.time() - self.start
        self.updateGUI(stamp="Time Temp_Feedthroughs", data=self.ttemp_ft)
        self.updateGUI(stamp="Temp_Feedthrough_Left", data=self.temp_ftl)
        self.updateGUI(stamp="Temp_Feedthrough_Right", data=self.temp_ftr)
        print "time: %.0f s\ttemp_feedthrough_left: %f C" % (self.ttemp_ft, self.temp_ftl)
        print "time: %.0f s\ttemp_feedthrough_right: %f C" % (self.ttemp_ft, self.temp_ftr)


        #time.sleep(.1)

        # get sample temp and setpoint
        self.temp_sample = self.pid.get_pv()
        self.setpoint_sample = self.pid.get_setpoint()
        self.ttemp_sample = time.time() - self.start
        self.updateGUI(stamp="Time Temp_Sample", data=self.ttemp_sample)
        self.updateGUI(stamp="Temp_Sample", data=self.temp_sample)
        self.updateGUI(stamp="Setpoint_Sample", data=self.setpoint_sample)
        print "time: %.0f s\ttemp_sample: %f C" % (self.ttemp_sample, self.temp_sample)
        print "time: %.0f s\tsetpoint_sample: %f C" % (self.ttemp_sample, self.setpoint_sample)
        time.sleep(.1)
    #end def

    #--------------------------------------------------------------------------
    def write_data_to_file(self):
        global myfile
        print('Write data to file')
        time = np.average([self.tdisp,self.tpressure_cyl,self.tvacuum,self.ttemp_sample])
        myfile.write('%.1f,%.3f,%.3f,%.3f,%.3f,%.1f,%.1f,%.1f\n' % (time, self.disp, self.pressure_cyl, self.pressure_sample * 10**-6, self.vacuum * 10**3, self.temp_sample, self.setpoint_sample, self.temp_ftl, self.temp_ftr) )
    #end def

    #--------------------------------------------------------------------------
    def updateGUI(self, stamp, data):
        """
        Sends data to the GUI (main thread), for live updating while the process is running
        in another thread.
        """
        time.sleep(0.1)
        wx.CallAfter(pub.sendMessage, stamp, msg=data)
    #end def

    #--------------------------------------------------------------------------
    def save_files(self):
        ''' Function saving the files after the data acquisition loop has been
            exited.
        '''

        print('Save Files')
        global myfile
        myfile.close() # Close the file

        # Save the GUI plots
        global save_plots_ID
        save_plots_ID = 1
        self.updateGUI(stamp='Save_All', data='Save')
    #end def
#end class
###############################################################################

###############################################################################
class BoundControlBox(wx.Panel):
    """ A static box with a couple of radio buttons and a text
        box. Allows to switch between an automatic mode and a
        manual mode with an associated value.
    """
    #--------------------------------------------------------------------------
    def __init__(self, parent, ID, label, initval):
        wx.Panel.__init__(self, parent, ID)

        self.value = initval

        box = wx.StaticBox(self, -1, label)
        sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        self.radio_auto = wx.RadioButton(self, -1, label="Auto", style=wx.RB_GROUP)
        self.radio_manual = wx.RadioButton(self, -1, label="Manual")
        self.manual_text = wx.TextCtrl(self, -1,
            size=(30,-1),
            value=str(initval),
            style=wx.TE_PROCESS_ENTER)

        self.Bind(wx.EVT_UPDATE_UI, self.on_update_manual_text, self.manual_text)
        self.Bind(wx.EVT_TEXT_ENTER, self.on_text_enter, self.manual_text)

        manual_box = wx.BoxSizer(wx.HORIZONTAL)
        manual_box.Add(self.radio_manual, flag=wx.ALIGN_CENTER_VERTICAL)
        manual_box.Add(self.manual_text, flag=wx.ALIGN_CENTER_VERTICAL)

        sizer.Add(self.radio_auto, 0, wx.ALL, 10)
        sizer.Add(manual_box, 0, wx.ALL, 10)

        self.SetSizer(sizer)
        sizer.Fit(self)

    #end init

    #--------------------------------------------------------------------------
    def on_update_manual_text(self, event):
        self.manual_text.Enable(self.radio_manual.GetValue())

    #end def

    #--------------------------------------------------------------------------
    def on_text_enter(self, event):
        self.value = self.manual_text.GetValue()

    #end def

    #--------------------------------------------------------------------------
    def is_auto(self):
        return self.radio_auto.GetValue()

    #end def

    #--------------------------------------------------------------------------
    def manual_value(self):
        return self.value

    #end def

#end class
###############################################################################


###############################################################################
class UserPanel(wx.Panel):
    """
    Control Panel
    """
    #--------------------------------------------------------------------------
    def __init__(self, *args, **kwargs):
        wx.Panel.__init__(self, *args, **kwargs)

        self.create_title("Control Panel") # Title

        self.font2 = wx.Font(11, wx.DEFAULT, wx.NORMAL, wx.NORMAL)


        self.run_stop() # Run and Stop buttons

        self.create_sizer() # Set Sizer for panel

        pub.subscribe(self.enable_buttons, "Enable Buttons")
    #--------------------------------------------------------------------------
    def create_title(self, name):
        self.titlePanel = wx.Panel(self, -1)
        title = wx.StaticText(self.titlePanel, label=name)
        font_title = wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.BOLD)
        title.SetFont(font_title)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add((0,-1))
        hbox.Add(title, 0, wx.LEFT, 5)

        self.titlePanel.SetSizer(hbox)
    #end def

    #--------------------------------------------------------------------------
    def run_stop(self):
        self.run_stopPanel = wx.Panel(self, -1)
        rs_sizer = wx.GridBagSizer(2, 3)

        self.btn_run = btn_run = wx.Button(self.run_stopPanel, label='run', style=0, size=(60,30)) # Run Button
        btn_run.SetBackgroundColour((0,255,0))
        caption_run = wx.StaticText(self.run_stopPanel, label='*run measurement')
        self.btn_stop = btn_stop = wx.Button(self.run_stopPanel, label='stop', style=0, size=(60,30)) # Stop Button
        btn_stop.SetBackgroundColour((255,0,0))
        caption_stop = wx.StaticText(self.run_stopPanel, label = '*quit operation')
        self.btn_zero = btn_zero = wx.Button(self.run_stopPanel, label='zero', style=0, size=(60,30)) # Stop Button
        btn_zero.SetBackgroundColour((0,0,255))
        caption_zero = wx.StaticText(self.run_stopPanel, label = '*zero out displacement')


        btn_run.Bind(wx.EVT_BUTTON, self.run)
        btn_stop.Bind(wx.EVT_BUTTON, self.stop)
        btn_zero.Bind(wx.EVT_BUTTON, self.zero)

        rs_sizer.Add(btn_run,(0,0),flag=wx.ALIGN_CENTER_HORIZONTAL)
        rs_sizer.Add(caption_run,(1,0),flag=wx.ALIGN_CENTER_HORIZONTAL)
        rs_sizer.Add(btn_zero, (0,1),flag=wx.ALIGN_CENTER_HORIZONTAL)
        rs_sizer.Add(caption_zero, (1,1),flag=wx.ALIGN_CENTER_HORIZONTAL)
        rs_sizer.Add(btn_stop,(0,2),flag=wx.ALIGN_CENTER_HORIZONTAL)
        rs_sizer.Add(caption_stop,(1,2),flag=wx.ALIGN_CENTER_HORIZONTAL)


        self.run_stopPanel.SetSizer(rs_sizer)

        btn_stop.Disable()

    # end def

    #--------------------------------------------------------------------------
    def run(self, event):
        global dataFile
        global myfile
        global abort_ID


        try:
            self.name_folder()

            if self.run_check == wx.ID_OK:

                begin = datetime.now() # Current date and time
                file = dataFile # creates a data file
                myfile = open(dataFile, 'w') # opens file for writing/overwriting
                myfile.write('hot press data\nstart time: ' + str(begin) + '\n')
                myfile.write('run time (s), displacement (mm), cylinder pressure (PSI), sample pressure (MPa), vacuum pressure (mTorr), sample temperature (C), sample setpoint temp (C), left feedthrough temperature (C),right feedthrough temperature (C)\n')

                abort_ID = 0

                #start the threading process
                thread = ProcessThread()
                self.btn_run.Disable()
                self.btn_zero.Disable()
                self.btn_stop.Enable()
            #end if

        #end try

        except visa.VisaIOError:
            wx.MessageBox("Not all instruments are connected!", "Error")
        #end except

    #end def

    #--------------------------------------------------------------------------
    def name_folder(self):
        question = wx.MessageDialog(None, 'The data files are saved into a folder upon ' + \
                    'completion. \nBy default, the folder will be named with a time stamp.\n\n' + \
                    'Would you like to name your own folder?', 'Question',
                    wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
        answer = question.ShowModal()

        if answer == wx.ID_YES:
            self.folder_name = wx.GetTextFromUser('Enter the name of your folder.\n' + \
                                                'Only type in a name, NOT a file path.')
            if self.folder_name == "":
                wx.MessageBox("Canceled")
            else:
                self.choose_dir()

        #end if

        else:
            date = str(datetime.now())
            self.folder_name = 'Hot Press Data %s.%s.%s' % (date[0:13], date[14:16], date[17:19])

            self.choose_dir()

        #end else

    #end def

    #--------------------------------------------------------------------------
    def choose_dir(self):
        found = False

        dlg = wx.DirDialog (None, "Choose the directory to save your files.", "",
                    wx.DD_DEFAULT_STYLE)

        self.run_check = dlg.ShowModal()

        if self.run_check == wx.ID_OK:
            global filePath
            filePath = dlg.GetPath()

            filePath = filePath + '/' + self.folder_name

            if not os.path.exists(filePath):
                os.makedirs(filePath)
                os.chdir(filePath)
            else:
                n = 1

                while found == False:
                    path = filePath + ' - ' + str(n)

                    if os.path.exists(path):
                        n = n + 1
                    else:
                        os.makedirs(path)
                        os.chdir(path)
                        n = 1
                        found = True

                #end while

            #end else

        #end if

        # Set the global path to the newly created path, if applicable.
        if found == True:
            filePath = path
        #end if
    #end def

    #--------------------------------------------------------------------------
    def stop(self, event):
        global abort_ID
        abort_ID = 1

        self.enable_buttons
    #end def

    #--------------------------------------------------------------------------
    def zero(self,event):
        global lj

        lj.zero_displacement()
    #end def

    #--------------------------------------------------------------------------
    def create_sizer(self):

        sizer = wx.GridBagSizer(2,1)
        sizer.Add(self.titlePanel, (0, 1), flag=wx.ALIGN_CENTER_HORIZONTAL)
        sizer.Add(self.run_stopPanel, (1,1), flag=wx.ALIGN_CENTER_HORIZONTAL)

        self.SetSizer(sizer)

    #end def

    #--------------------------------------------------------------------------
    def enable_buttons(self):
        self.btn_run.Enable()
        self.btn_zero.Enable()
        self.btn_stop.Disable()

    #end def

#end class
###############################################################################

###############################################################################
class StatusPanel(wx.Panel):
    """
    Current Status of Measurements
    """
    #--------------------------------------------------------------------------
    def __init__(self, *args, **kwargs):
        wx.Panel.__init__(self, *args, **kwargs)

        self.celsius = u"\u2103"
        self.delta = u"\u0394"
        self.mu = u"\u00b5"

        self.ctime = str(datetime.now())[11:19]
        self.t='0:00:00'
        self.pressure_cyl = str(0)
        self.pressure_sample = str(0)
        self.pressure_chamber = str(0)
        self.temp_sample = str(30)
        self.setpoint_sample = str(30)
        self.temp_ft_left = str(30)
        self.temp_ft_right = str(30)
        self.displacement = str(0)

        self.create_title("System Status")

        self.linebreak1 = wx.StaticLine(self, pos=(-1,-1), size=(300,1))
        self.create_status()
        self.linebreak2 = wx.StaticLine(self, pos=(-1,-1), size=(300,1))

        self.linebreak3 = wx.StaticLine(self, pos=(-1,-1), size=(1,300), style=wx.LI_VERTICAL)


        # Updates from running program
        pub.subscribe(self.OnTime, "Time Pressure_Cyl")
        pub.subscribe(self.OnTime, "Time Pressure_Chamber")
        pub.subscribe(self.OnTime, "Time Pressure_Sample")
        pub.subscribe(self.OnTime, "Time Temp_Sample")
        pub.subscribe(self.OnTime, "Time Temp_Feedthroughs")
        pub.subscribe(self.OnTime, "Time Displacement")

        pub.subscribe(self.OnPressureCyl, "Pressure_Cyl")
        pub.subscribe(self.OnPressureChamber, "Pressure_Chamber")
        pub.subscribe(self.OnPressureSample, "Pressure_Sample")

        pub.subscribe(self.OnTempSample, "Temp_Sample")
        pub.subscribe(self.OnSetpointSample, "Setpoint_Sample")
        pub.subscribe(self.OnTempFTL, "Temp_Feedthrough_Left")
        pub.subscribe(self.OnTempFTR, "Temp_Feedthrough_Right")

        pub.subscribe(self.OnDisplacement, "Displacement")

        #self.update_values()
        self.create_sizer()
    #end init


    #--------------------------------------------------------------------------
    def OnPressureChamber(self, msg):
        self.pressure_chamber = '%.1f'%(float(msg)*10**3)
        self.update_values()
    #end def

    #--------------------------------------------------------------------------
    def OnPressureCyl(self, msg):
        self.pressure_cyl = '%.1f'%(float(msg))
        self.update_values()
    #end def

    #--------------------------------------------------------------------------
    def OnPressureSample(self, msg):
        self.pressure_sample = '%.1f'%(float(msg)*10**-6)
        self.update_values()
    #end def

    #--------------------------------------------------------------------------
    def OnTempSample(self, msg):
        self.temp_sample = '%.1f'%(float(msg))
        self.update_values()
    #end def

    #--------------------------------------------------------------------------
    def OnSetpointSample(self, msg):
        self.setpoint_sample = '%.1f'%(float(msg))
        self.update_values()
    #end def

    #--------------------------------------------------------------------------
    def OnTempFTL(self, msg):
        self.temp_ft_left = '%.1f'%(float(msg))
        self.update_values()
    #end def

    #--------------------------------------------------------------------------
    def OnTempFTR(self, msg):
        self.temp_ft_right = '%.1f'%(float(msg))
        self.update_values()
    #end def

    #--------------------------------------------------------------------------
    def OnDisplacement(self, msg):
        self.displacement = '%.3f'%(float(msg))
        self.update_values()
    #end def

    #--------------------------------------------------------------------------
    def OnTime(self, msg):
        time = int(float(msg))

        hours = str(time/3600)
        minutes = int(time%3600/60)
        if (minutes < 10):
            minutes = '0%i'%(minutes)
        else:
            minutes = '%i'%(minutes)
        seconds = int(time%60)
        if (seconds < 10):
            seconds = '0%i'%(seconds)
        else:
            seconds = '%i'%(seconds)

        self.t = '%s:%s:%s'%(hours,minutes,seconds)
        self.ctime = str(datetime.now())[11:19]
        self.update_values()
    #end def

    #--------------------------------------------------------------------------
    def create_title(self, name):
        self.titlePanel = wx.Panel(self, -1)
        title = wx.StaticText(self.titlePanel, label=name)
        font_title = wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.BOLD)
        title.SetFont(font_title)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add((0,-1))
        hbox.Add(title, 0, wx.LEFT, 5)

        self.titlePanel.SetSizer(hbox)
    #end def

    #--------------------------------------------------------------------------
    def create_status(self):
        self.label_ctime = wx.StaticText(self, label="current time:")
        self.label_ctime.SetFont(wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.NORMAL))
        self.label_t = wx.StaticText(self, label="run time (s):")
        self.label_t.SetFont(wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.NORMAL))
        self.label_press_cyl = wx.StaticText(self, label="pressure_cylinder (PSI):")
        self.label_press_cyl.SetFont(wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.NORMAL))
        self.label_press_sample = wx.StaticText(self, label="pressure_sample (MPa):")
        self.label_press_sample.SetFont(wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.NORMAL))
        self.label_press_chamber = wx.StaticText(self, label="pressure_vacuum (mTorr):")
        self.label_press_chamber.SetFont(wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.NORMAL))
        self.label_temp_sample = wx.StaticText(self, label="temp_sample ("+self.celsius+"):")
        self.label_temp_sample.SetFont(wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.NORMAL))
        self.label_setpoint_sample = wx.StaticText(self, label="setpoint_sample ("+self.celsius+"):")
        self.label_setpoint_sample.SetFont(wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.NORMAL))
        self.label_temp_ftl = wx.StaticText(self, label="temp_feedthrough_left ("+self.celsius+"):")
        self.label_temp_ftl.SetFont(wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.NORMAL))
        self.label_temp_ftr = wx.StaticText(self, label="temp_feedthrough_right ("+self.celsius+"):")
        self.label_temp_ftr.SetFont(wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.NORMAL))
        self.label_displacement = wx.StaticText(self, label="displacement (mm):")
        self.label_displacement.SetFont(wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.NORMAL))

        self.ctimecurrent = wx.StaticText(self, label=self.ctime)
        self.ctimecurrent.SetFont(wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.NORMAL))
        self.tcurrent = wx.StaticText(self, label=self.t)
        self.tcurrent.SetFont(wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.NORMAL))
        self.presscylcurrent = wx.StaticText(self, label=self.pressure_cyl)
        self.presscylcurrent.SetFont(wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.NORMAL))
        self.presssamplecurrent = wx.StaticText(self, label=self.pressure_sample)
        self.presssamplecurrent.SetFont(wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.NORMAL))
        self.presschambercurrent = wx.StaticText(self, label=self.pressure_chamber)
        self.presschambercurrent.SetFont(wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.NORMAL))
        self.tempsamplecurrent = wx.StaticText(self, label=self.temp_sample)
        self.tempsamplecurrent.SetFont(wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.NORMAL))
        self.setpointsamplecurrent = wx.StaticText(self, label=self.setpoint_sample)
        self.setpointsamplecurrent.SetFont(wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.NORMAL))
        self.tempftlcurrent = wx.StaticText(self, label=self.temp_ft_left)
        self.tempftlcurrent.SetFont(wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.NORMAL))
        self.tempftrcurrent = wx.StaticText(self, label=self.temp_ft_right)
        self.tempftrcurrent.SetFont(wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.NORMAL))
        self.displacementcurrent = wx.StaticText(self, label=self.displacement)
        self.displacementcurrent.SetFont(wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.NORMAL))
    #end def

    #--------------------------------------------------------------------------
    def update_values(self):
        self.ctimecurrent.SetLabel(self.ctime)
        self.tcurrent.SetLabel(self.t)
        self.presscylcurrent.SetLabel(self.pressure_cyl)
        self.presssamplecurrent.SetLabel(self.pressure_sample)
        self.presschambercurrent.SetLabel(self.pressure_chamber)
        self.tempsamplecurrent.SetLabel(self.temp_sample)
        self.setpointsamplecurrent.SetLabel(self.setpoint_sample)
        self.tempftlcurrent.SetLabel(self.temp_ft_left)
        self.tempftrcurrent.SetLabel(self.temp_ft_right)
        self.displacementcurrent.SetLabel(self.displacement)
    #end def

    #--------------------------------------------------------------------------
    def create_sizer(self):
        sizer = wx.GridBagSizer(12,2)

        sizer.Add(self.titlePanel, (0, 0), span = (1,2), border=5, flag=wx.ALIGN_CENTER_HORIZONTAL)

        sizer.Add(self.linebreak1,(1,0), span = (1,2))

        sizer.Add(self.label_ctime, (2,0))
        sizer.Add(self.ctimecurrent, (2, 1),flag=wx.ALIGN_CENTER_HORIZONTAL)
        sizer.Add(self.label_t, (3,0))
        sizer.Add(self.tcurrent, (3, 1),flag=wx.ALIGN_CENTER_HORIZONTAL)

        sizer.Add(self.label_press_cyl, (4, 0))
        sizer.Add(self.presscylcurrent, (4, 1),flag=wx.ALIGN_CENTER_HORIZONTAL)
        sizer.Add(self.label_press_sample, (5, 0))
        sizer.Add(self.presssamplecurrent, (5, 1),flag=wx.ALIGN_CENTER_HORIZONTAL)
        sizer.Add(self.label_press_chamber, (6, 0))
        sizer.Add(self.presschambercurrent, (6, 1),flag=wx.ALIGN_CENTER_HORIZONTAL)

        sizer.Add(self.label_temp_sample, (7,0))
        sizer.Add(self.tempsamplecurrent, (7,1),flag=wx.ALIGN_CENTER_HORIZONTAL)
        sizer.Add(self.label_setpoint_sample, (8,0))
        sizer.Add(self.setpointsamplecurrent, (8,1),flag=wx.ALIGN_CENTER_HORIZONTAL)
        sizer.Add(self.label_temp_ftl, (9,0))
        sizer.Add(self.tempftlcurrent, (9,1),flag=wx.ALIGN_CENTER_HORIZONTAL)
        sizer.Add(self.label_temp_ftr, (10,0))
        sizer.Add(self.tempftrcurrent, (10,1),flag=wx.ALIGN_CENTER_HORIZONTAL)

        sizer.Add(self.label_displacement, (11,0))
        sizer.Add(self.displacementcurrent, (11,1),flag=wx.ALIGN_CENTER_HORIZONTAL)

        sizer.Add(self.linebreak2, (12,0), span = (1,2))

        self.SetSizer(sizer)
    #end def

#end class
###############################################################################

###############################################################################
class DisplacementPanel(wx.Panel):
    """
    GUI Window for plotting voltage data.
    """
    #--------------------------------------------------------------------------
    def __init__(self, *args, **kwargs):
        wx.Panel.__init__(self, *args, **kwargs)
        global filePath

        global tdisp_list, disp_list

        self.create_title("Cylinder Displacement")
        self.init_plot()
        self.canvas = FigureCanvasWxAgg(self, -1, self.figure)
        self.create_control_panel()
        self.create_sizer()

        pub.subscribe(self.OnDisp, "Displacement")
        pub.subscribe(self.OnDispTime, "Time Displacement")

        # For saving the plots at the end of data acquisition:
        pub.subscribe(self.save_plot, "Save_All")

        self.animator = animation.FuncAnimation(self.figure, self.draw_plot, interval=500, blit=False)
    #end init

    #--------------------------------------------------------------------------
    def create_title(self, name):
        self.titlePanel = wx.Panel(self, -1)
        title = wx.StaticText(self.titlePanel, label=name)
        font_title = wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.BOLD)
        title.SetFont(font_title)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add((0,-1))
        hbox.Add(title, 0, wx.LEFT, 5)

        self.titlePanel.SetSizer(hbox)
    #end def

    #--------------------------------------------------------------------------
    def create_control_panel(self):

        self.xmin_control = BoundControlBox(self, -1, "t min", 0)
        self.xmax_control = BoundControlBox(self, -1, "t max", 1000)
        self.ymin_control = BoundControlBox(self, -1, "d min", -5)
        self.ymax_control = BoundControlBox(self, -1, "d max", 5)

        self.hbox1 = wx.BoxSizer(wx.HORIZONTAL)
        self.hbox1.AddSpacer(10)
        self.hbox1.Add(self.xmin_control, border=5, flag=wx.ALL)
        self.hbox1.Add(self.xmax_control, border=5, flag=wx.ALL)
        self.hbox1.AddSpacer(10)
        self.hbox1.Add(self.ymin_control, border=5, flag=wx.ALL)
        self.hbox1.Add(self.ymax_control, border=5, flag=wx.ALL)
    #end def

    #--------------------------------------------------------------------------
    def OnDisp(self, msg):
        self.disp = float(msg)
        tdisp_list.append(self.tdisp)
        disp_list.append(self.disp)
    #end def

    #--------------------------------------------------------------------------
    def OnDispTime(self, msg):
        self.tdisp = float(msg)

    #end def

    #--------------------------------------------------------------------------
    def init_plot(self):
        self.dpi = 100
        self.colorDisp = 'g'

        self.figure = Figure((6.5,3.25), dpi=self.dpi)
        self.subplot = self.figure.add_subplot(111)
        self.lineDisp, = self.subplot.plot(tdisp_list,disp_list, color=self.colorDisp, linewidth=1)
        self.legend = self.figure.legend( (self.lineDisp,), (r"$d$",), (0.15,0.75),fontsize=10)
        #self.subplot.text(0.05, .95, r'$X(f) = \mathcal{F}\{x(t)\}$', \
            #verticalalignment='top', transform = self.subplot.transAxes)
    #end def

    #--------------------------------------------------------------------------
    def draw_plot(self,i):
        self.subplot.clear()
        #self.subplot.set_title("voltage vs. time", fontsize=12)
        self.subplot.set_ylabel(r"displacement (mm)", fontsize = 8)
        self.subplot.set_xlabel("time (s)", fontsize = 8)

        # Adjustable scale:
        if self.xmax_control.is_auto():
            xmax = max(tdisp_list)
        else:
            xmax = float(self.xmax_control.manual_value())
        if self.xmin_control.is_auto():
            xmin = 0
        else:
            xmin = float(self.xmin_control.manual_value())
        if self.ymin_control.is_auto():
            mind = min(disp_list)
            ymin = mind - abs(mind)*0.3
        else:
            ymin = float(self.ymin_control.manual_value())
        if self.ymax_control.is_auto():
            maxd = max(disp_list)
            ymax = maxd + maxd*0.5
        else:
            ymax = float(self.ymax_control.manual_value())


        self.subplot.set_xlim([xmin, xmax])
        self.subplot.set_ylim([ymin, ymax])

        pylab.setp(self.subplot.get_xticklabels(), fontsize=8)
        pylab.setp(self.subplot.get_yticklabels(), fontsize=8)

        self.lineDisp, = self.subplot.plot(tdisp_list,disp_list, color=self.colorDisp, linewidth=1)

        return (self.lineDisp,)
        #return (self.subplot.plot( thighV_list, highV_list, color=self.colorH, linewidth=1),
            #self.subplot.plot( tlowV_list, lowV_list, color=self.colorL, linewidth=1))

    #end def

    #--------------------------------------------------------------------------
    def save_plot(self, msg):
        path = filePath + "/Displacement_Plot.png"
        self.canvas.print_figure(path)

    #end def

    #--------------------------------------------------------------------------
    def create_sizer(self):
        sizer = wx.GridBagSizer(3,1)
        sizer.Add(self.titlePanel, (0, 0), flag=wx.ALIGN_CENTER_HORIZONTAL)
        sizer.Add(self.canvas, ( 1,0), flag=wx.ALIGN_CENTER_HORIZONTAL)
        sizer.Add(self.hbox1, (2,0), flag=wx.ALIGN_CENTER_HORIZONTAL)

        self.SetSizer(sizer)
    #end def

#end class
###############################################################################

###############################################################################
class TemperaturePanel(wx.Panel):
    """
    GUI Window for plotting temperature data.
    """
    #--------------------------------------------------------------------------
    def __init__(self, *args, **kwargs):
        wx.Panel.__init__(self, *args, **kwargs)
        global filePath

        global ttemp_sample_list
        global temp_sample_list
        global setpoint_sample_list

        self.create_title("Sample Temperature")
        self.init_plot()
        self.canvas = FigureCanvasWxAgg(self, -1, self.figure)
        self.create_control_panel()
        self.create_sizer()

        pub.subscribe(self.OnTimeTempSample, "Time Temp_Sample")
        pub.subscribe(self.OnTempSample, "Temp_Sample")
        pub.subscribe(self.OnSetpointSample, "Setpoint_Sample")


        # For saving the plots at the end of data acquisition:
        pub.subscribe(self.save_plot, "Save_All")

        self.animator = animation.FuncAnimation(self.figure, self.draw_plot, interval=500, blit=False)
    #end init

    #--------------------------------------------------------------------------
    def create_title(self, name):
        self.titlePanel = wx.Panel(self, -1)
        title = wx.StaticText(self.titlePanel, label=name)
        font_title = wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.BOLD)
        title.SetFont(font_title)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add((0,-1))
        hbox.Add(title, 0, wx.LEFT, 5)

        self.titlePanel.SetSizer(hbox)
    #end def

    #--------------------------------------------------------------------------
    def create_control_panel(self):

        self.xmin_control = BoundControlBox(self, -1, "t min", 0)
        self.xmax_control = BoundControlBox(self, -1, "t max", 1000)
        self.ymin_control = BoundControlBox(self, -1, "T min", 0)
        self.ymax_control = BoundControlBox(self, -1, "T max", 1000)

        self.hbox1 = wx.BoxSizer(wx.HORIZONTAL)
        self.hbox1.AddSpacer(10)
        self.hbox1.Add(self.xmin_control, border=5, flag=wx.ALL)
        self.hbox1.Add(self.xmax_control, border=5, flag=wx.ALL)
        self.hbox1.AddSpacer(10)
        self.hbox1.Add(self.ymin_control, border=5, flag=wx.ALL)
        self.hbox1.Add(self.ymax_control, border=5, flag=wx.ALL)
    #end def

    #--------------------------------------------------------------------------
    def OnTimeTempSample(self, msg):
        self.ttemp_sample = float(msg)

    #end def

    #--------------------------------------------------------------------------
    def OnTempSample(self, msg):
        self.temp_sample = float(msg)
        ttemp_sample_list.append(self.ttemp_sample)
        temp_sample_list.append(self.temp_sample)
    #end def

    #--------------------------------------------------------------------------
    def OnSetpointSample(self, msg):
        self.setpoint_sample = float(msg)
        setpoint_sample_list.append(self.setpoint_sample)
    #end def

    #--------------------------------------------------------------------------
    def init_plot(self):
        self.dpi = 100
        self.colorTsample = 'r'
        self.colorSPsample = 'b'

        self.figure = Figure((6.5,3.25), dpi=self.dpi)
        self.subplot = self.figure.add_subplot(111)

        self.lineTsample, = self.subplot.plot(ttemp_sample_list,temp_sample_list, color=self.colorTsample, linewidth=1)
        self.lineSPsample, = self.subplot.plot(ttemp_sample_list,setpoint_sample_list, color=self.colorSPsample, linewidth=1)
        self.legend = self.figure.legend( (self.lineTsample,self.lineSPsample), (r"$T_{sample}$",r"$SP_{sample}"), (0.15,0.75),fontsize=10)
        #self.subplot.text(0.05, .95, r'$X(f) = \mathcal{F}\{x(t)\}$', \
            #verticalalignment='top', transform = self.subplot.transAxes)
    #end def

    #--------------------------------------------------------------------------
    def draw_plot(self,i):
        self.subplot.clear()
        #self.subplot.set_title("temperature vs. time", fontsize=12)
        self.subplot.set_ylabel(r"temperature ($\degree$C)", fontsize = 8)
        self.subplot.set_xlabel("time (s)", fontsize = 8)

        # Adjustable scale:
        if self.xmax_control.is_auto():
            xmax = max(ttemp_sample_list)
        else:
            xmax = float(self.xmax_control.manual_value())
        if self.xmin_control.is_auto():
            xmin = 0
        else:
            xmin = float(self.xmin_control.manual_value())
        if self.ymin_control.is_auto():
            minT = min(temp_sample_list+setpoint_sample_list)
            ymin = minT - abs(minT)*0.3
        else:
            ymin = float(self.ymin_control.manual_value())
        if self.ymax_control.is_auto():
            maxT = max(temp_sample_list+setpoint_sample_list)
            ymax = maxT + abs(maxT)*0.3
        else:
            ymax = float(self.ymax_control.manual_value())

        self.subplot.set_xlim([xmin, xmax])
        self.subplot.set_ylim([ymin, ymax])

        pylab.setp(self.subplot.get_xticklabels(), fontsize=8)
        pylab.setp(self.subplot.get_yticklabels(), fontsize=8)

        self.lineTsample, = self.subplot.plot(ttemp_sample_list,temp_sample_list, color=self.colorTsample, linewidth=1)
        self.lineSPsample, = self.subplot.plot(ttemp_sample_list,setpoint_sample_list, color=self.colorSPsample, linewidth=1)
        return (self.lineTsample, self.lineSPsample)

    #end def

    #--------------------------------------------------------------------------
    def save_plot(self, msg):
        path = filePath + "/Temperature_Plot.png"
        self.canvas.print_figure(path)

    #end def

    #--------------------------------------------------------------------------
    def create_sizer(self):
        sizer = wx.GridBagSizer(3,1)
        sizer.Add(self.titlePanel, (0, 0),flag=wx.ALIGN_CENTER_HORIZONTAL)
        sizer.Add(self.canvas, ( 1,0),flag=wx.ALIGN_CENTER_HORIZONTAL)
        sizer.Add(self.hbox1, (2,0),flag=wx.ALIGN_CENTER_HORIZONTAL)

        self.SetSizer(sizer)
    #end def

#end class
###############################################################################

###############################################################################
class SamplePressurePanel(wx.Panel):
    """
    GUI Window for plotting voltage data.
    """
    #--------------------------------------------------------------------------
    def __init__(self, *args, **kwargs):
        wx.Panel.__init__(self, *args, **kwargs)
        global filePath

        global tpress_sample_list, press_sample_list

        self.create_title("Sample Pressure")
        self.init_plot()
        self.canvas = FigureCanvasWxAgg(self, -1, self.figure)
        self.create_control_panel()
        self.create_sizer()

        pub.subscribe(self.OnPress, "Pressure_Sample")
        pub.subscribe(self.OnPressTime, "Time Pressure_Sample")

        # For saving the plots at the end of data acquisition:
        pub.subscribe(self.save_plot, "Save_All")

        self.animator = animation.FuncAnimation(self.figure, self.draw_plot, interval=500, blit=False)
    #end init

    #--------------------------------------------------------------------------
    def create_title(self, name):
        self.titlePanel = wx.Panel(self, -1)
        title = wx.StaticText(self.titlePanel, label=name)
        font_title = wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.BOLD)
        title.SetFont(font_title)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add((0,-1))
        hbox.Add(title, 0, wx.LEFT, 5)

        self.titlePanel.SetSizer(hbox)
    #end def

    #--------------------------------------------------------------------------
    def create_control_panel(self):

        self.xmin_control = BoundControlBox(self, -1, "t min", 0)
        self.xmax_control = BoundControlBox(self, -1, "t max", 1000)
        self.ymin_control = BoundControlBox(self, -1, "P min", 0)
        self.ymax_control = BoundControlBox(self, -1, "P max", 100)

        self.hbox1 = wx.BoxSizer(wx.HORIZONTAL)
        self.hbox1.AddSpacer(10)
        self.hbox1.Add(self.xmin_control, border=5, flag=wx.ALL)
        self.hbox1.Add(self.xmax_control, border=5, flag=wx.ALL)
        self.hbox1.AddSpacer(10)
        self.hbox1.Add(self.ymin_control, border=5, flag=wx.ALL)
        self.hbox1.Add(self.ymax_control, border=5, flag=wx.ALL)
    #end def

    #--------------------------------------------------------------------------
    def OnPress(self, msg):
        self.press = float(msg)
        tpress_sample_list.append(self.tpress)
        press_sample_list.append(self.press * 10**-6)
    #end def

    #--------------------------------------------------------------------------
    def OnPressTime(self, msg):
        self.tpress = float(msg)

    #end def

    #--------------------------------------------------------------------------
    def init_plot(self):
        self.dpi = 100
        self.colorPress = 'b'

        self.figure = Figure((6.5,3.25), dpi=self.dpi)
        self.subplot = self.figure.add_subplot(111)
        self.linePress, = self.subplot.plot(tpress_sample_list,press_sample_list, color=self.colorPress, linewidth=1)
        self.legend = self.figure.legend( (self.linePress,), (r"$P_{sample}$",), (0.15,0.75),fontsize=10)
        #self.subplot.text(0.05, .95, r'$X(f) = \mathcal{F}\{x(t)\}$', \
            #verticalalignment='top', transform = self.subplot.transAxes)
    #end def

    #--------------------------------------------------------------------------
    def draw_plot(self,i):
        self.subplot.clear()
        #self.subplot.set_title("voltage vs. time", fontsize=12)
        self.subplot.set_ylabel("pressure (MPa)", fontsize = 8)
        self.subplot.set_xlabel("time (s)", fontsize = 8)

        # Adjustable scale:
        if self.xmax_control.is_auto():
            xmax = max(tpress_sample_list)
        else:
            xmax = float(self.xmax_control.manual_value())
        if self.xmin_control.is_auto():
            xmin = 0
        else:
            xmin = float(self.xmin_control.manual_value())
        if self.ymin_control.is_auto():
            minP = min(press_sample_list)
            ymin = minP - abs(minP)*0.3
        else:
            ymin = float(self.ymin_control.manual_value())
        if self.ymax_control.is_auto():
            maxP = max(press_sample_list)
            ymax = maxP + abs(maxP)*0.3
        else:
            ymax = float(self.ymax_control.manual_value())

        self.subplot.set_xlim([xmin, xmax])
        self.subplot.set_ylim([ymin, ymax])

        pylab.setp(self.subplot.get_xticklabels(), fontsize=8)
        pylab.setp(self.subplot.get_yticklabels(), fontsize=8)

        self.linePress, = self.subplot.plot(tpress_sample_list,press_sample_list, color=self.colorPress, linewidth=1)

        return (self.linePress,)
        #return (self.subplot.plot( thighV_list, highV_list, color=self.colorH, linewidth=1),
            #self.subplot.plot( tlowV_list, lowV_list, color=self.colorL, linewidth=1))

    #end def

    #--------------------------------------------------------------------------
    def save_plot(self, msg):
        path = filePath + "/Pressure_Sample_Plot.png"
        self.canvas.print_figure(path)

    #end def

    #--------------------------------------------------------------------------
    def create_sizer(self):
        sizer = wx.GridBagSizer(3,1)
        sizer.Add(self.titlePanel, (0, 0), flag=wx.ALIGN_CENTER_HORIZONTAL)
        sizer.Add(self.canvas, ( 1,0), flag=wx.ALIGN_CENTER_HORIZONTAL)
        sizer.Add(self.hbox1, (2,0), flag=wx.ALIGN_CENTER_HORIZONTAL)

        self.SetSizer(sizer)
    #end def

#end class
###############################################################################

###############################################################################
class ChamberPressurePanel(wx.Panel):
    """
    GUI Window for plotting voltage data.
    """
    #--------------------------------------------------------------------------
    def __init__(self, *args, **kwargs):
        wx.Panel.__init__(self, *args, **kwargs)
        global filePath

        global tpress_chamber_list, press_chamber_list

        self.create_title("Vacuum Pressure")
        self.init_plot()
        self.canvas = FigureCanvasWxAgg(self, -1, self.figure)
        self.create_control_panel()
        self.create_sizer()

        pub.subscribe(self.OnPress, "Pressure_Chamber")
        pub.subscribe(self.OnPressTime, "Time Pressure_Chamber")

        # For saving the plots at the end of data acquisition:
        pub.subscribe(self.save_plot, "Save_All")

        self.animator = animation.FuncAnimation(self.figure, self.draw_plot, interval=500, blit=False)
    #end init

    #--------------------------------------------------------------------------
    def create_title(self, name):
        self.titlePanel = wx.Panel(self, -1)
        title = wx.StaticText(self.titlePanel, label=name)
        font_title = wx.Font(16, wx.DEFAULT, wx.NORMAL, wx.BOLD)
        title.SetFont(font_title)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add((0,-1))
        hbox.Add(title, 0, wx.LEFT, 5)

        self.titlePanel.SetSizer(hbox)
    #end def

    #--------------------------------------------------------------------------
    def create_control_panel(self):

        self.xmin_control = BoundControlBox(self, -1, "t min", 0)
        self.xmax_control = BoundControlBox(self, -1, "t max", 1000)
        self.ymin_control = BoundControlBox(self, -1, "P min", 10**-4)
        self.ymax_control = BoundControlBox(self, -1, "P max", 10**3)

        self.hbox1 = wx.BoxSizer(wx.HORIZONTAL)
        self.hbox1.AddSpacer(10)
        self.hbox1.Add(self.xmin_control, border=5, flag=wx.ALL)
        self.hbox1.Add(self.xmax_control, border=5, flag=wx.ALL)
        self.hbox1.AddSpacer(10)
        self.hbox1.Add(self.ymin_control, border=5, flag=wx.ALL)
        self.hbox1.Add(self.ymax_control, border=5, flag=wx.ALL)
    #end def

    #--------------------------------------------------------------------------
    def OnPress(self, msg):
        self.press = float(msg)
        tpress_chamber_list.append(self.tpress)
        press_chamber_list.append(self.press)
    #end def

    #--------------------------------------------------------------------------
    def OnPressTime(self, msg):
        self.tpress = float(msg)

    #end def

    #--------------------------------------------------------------------------
    def init_plot(self):
        self.dpi = 100
        self.colorPress = 'c'

        self.figure = Figure((6.5,3.25), dpi=self.dpi)
        self.subplot = self.figure.add_subplot(111)
        self.linePress, = self.subplot.plot(tpress_chamber_list,press_chamber_list, color=self.colorPress, linewidth=1)
        self.legend = self.figure.legend( (self.linePress,), (r"$P_{vacuum}$",), (0.15,0.75),fontsize=10)
        #self.subplot.text(0.05, .95, r'$X(f) = \mathcal{F}\{x(t)\}$', \
            #verticalalignment='top', transform = self.subplot.transAxes)
    #end def

    #--------------------------------------------------------------------------
    def draw_plot(self,i):
        self.subplot.clear()
        #self.subplot.set_title("voltage vs. time", fontsize=12)
        self.subplot.set_ylabel("pressure (Torr)", fontsize = 8)
        self.subplot.set_xlabel("time (s)", fontsize = 8)

        # Adjustable scale:
        if self.xmax_control.is_auto():
            xmax = max(tpress_chamber_list)
        else:
            xmax = float(self.xmax_control.manual_value())
        if self.xmin_control.is_auto():
            xmin = 0
        else:
            xmin = float(self.xmin_control.manual_value())
        if self.ymin_control.is_auto():
            minP = min(press_chamber_list)
            ymin = minP/10
        else:
            ymin = float(self.ymin_control.manual_value())
        if self.ymax_control.is_auto():
            maxP = max(press_chamber_list)
            ymax = maxP*10
        else:
            ymax = float(self.ymax_control.manual_value())

        self.subplot.set_yscale('log')
        self.subplot.set_xlim([xmin, xmax])
        self.subplot.set_ylim([ymin, ymax])

        pylab.setp(self.subplot.get_xticklabels(), fontsize=8)
        pylab.setp(self.subplot.get_yticklabels(), fontsize=8)

        self.linePress, = self.subplot.plot(tpress_chamber_list,press_chamber_list, color=self.colorPress, linewidth=1)

        return (self.linePress,)
        #return (self.subplot.plot( thighV_list, highV_list, color=self.colorH, linewidth=1),
            #self.subplot.plot( tlowV_list, lowV_list, color=self.colorL, linewidth=1))

    #end def

    #--------------------------------------------------------------------------
    def save_plot(self, msg):
        path = filePath + "/Pressure_Chamber_Plot.png"
        self.canvas.print_figure(path)

    #end def

    #--------------------------------------------------------------------------
    def create_sizer(self):
        sizer = wx.GridBagSizer(3,1)
        sizer.Add(self.titlePanel, (0, 0), flag=wx.ALIGN_CENTER_HORIZONTAL)
        sizer.Add(self.canvas, ( 1,0), flag=wx.ALIGN_CENTER_HORIZONTAL)
        sizer.Add(self.hbox1, (2,0), flag=wx.ALIGN_CENTER_HORIZONTAL)

        self.SetSizer(sizer)
    #end def

#end class
###############################################################################

###############################################################################
class Frame(wx.Frame):
    """
    Main frame window in which GUI resides
    """
    #--------------------------------------------------------------------------
    def __init__(self, *args, **kwargs):
        wx.Frame.__init__(self, *args, **kwargs)
        self.init_UI()
        self.create_statusbar()
        self.create_menu()

        pub.subscribe(self.update_statusbar, "Status Bar")

    #end init

    #--------------------------------------------------------------------------
    def init_UI(self):
        self.SetBackgroundColour('#E0EBEB')
        self.userpanel = UserPanel(self,size=wx.DefaultSize)
        self.statuspanel = StatusPanel(self,size=wx.DefaultSize)
        self.displacementpanel = DisplacementPanel(self, size=wx.DefaultSize)
        self.temperaturepanel = TemperaturePanel(self, size=wx.DefaultSize)
        self.samplepressurepanel = SamplePressurePanel(self, size=wx.DefaultSize)
        self.chamberpressurepanel = ChamberPressurePanel(self, size=wx.DefaultSize)

        self.statuspanel.SetBackgroundColour('#ededed')

        sizer = wx.GridBagSizer(2, 3)
        sizer.Add(self.statuspanel, (0,0),flag=wx.ALIGN_CENTER_HORIZONTAL)
        sizer.Add(self.userpanel, (1,0), flag=wx.ALIGN_CENTER_HORIZONTAL)
        sizer.Add(self.displacementpanel, (0,1),flag=wx.ALIGN_CENTER_HORIZONTAL)
        sizer.Add(self.temperaturepanel, (1,1),flag=wx.ALIGN_CENTER_HORIZONTAL)
        sizer.Add(self.chamberpressurepanel, (0,2),flag=wx.ALIGN_CENTER_HORIZONTAL)
        sizer.Add(self.samplepressurepanel, (1,2),flag=wx.ALIGN_CENTER_HORIZONTAL)

        sizer.Fit(self)

        self.SetSizer(sizer)
        self.SetTitle('Hot Press Status GUI')
        self.Centre()
    #end def

    #--------------------------------------------------------------------------
    def create_menu(self):
        # Menu Bar with File, Quit
        menubar = wx.MenuBar()
        fileMenu = wx.Menu()
        qmi = wx.MenuItem(fileMenu, APP_EXIT, '&Quit\tCtrl+Q')
        #qmi.SetBitmap(wx.Bitmap('exit.png'))
        fileMenu.AppendItem(qmi)

        self.Bind(wx.EVT_MENU, self.onQuit, id=APP_EXIT)

        menubar.Append(fileMenu, 'File')
        self.SetMenuBar(menubar)
    #end def

    #--------------------------------------------------------------------------
    def onQuit(self, e):
        global abort_ID

        abort_ID=1
        self.Destroy()
        self.Close()

        sys.stdout.close()
        sys.stderr.close()
    #end def

    #--------------------------------------------------------------------------
    def create_statusbar(self):
        self.statusbar = ESB.EnhancedStatusBar(self, -1)
        self.statusbar.SetSize((-1, 23))
        self.statusbar.SetFieldsCount(4)
        self.SetStatusBar(self.statusbar)

        self.space_between = 10

        ### Create Widgets for the statusbar:
        # Status:
        self.status_text = wx.StaticText(self.statusbar, -1, "Ready")
        self.width0 = 105

        # Placer 1:
        placer1 = wx.StaticText(self.statusbar, -1, " ")

        # Title:
        #measurement_text = wx.StaticText(self.statusbar, -1, "Measurement Indicators:")
        #boldFont = wx.Font(9, wx.DEFAULT, wx.NORMAL, wx.BOLD)
        #measurement_text.SetFont(boldFont)
        #self.width1 = measurement_text.GetRect().width + self.space_between

        # Placer 2:
        placer2 = wx.StaticText(self.statusbar, -1, " ")

        # Version:
        version_label = wx.StaticText(self.statusbar, -1, "Version: %s" % version)
        self.width8 = version_label.GetRect().width + self.space_between

        # Set widths of each piece of the status bar:
        self.statusbar.SetStatusWidths([self.width0,50, -1, self.width8])

        ### Add the widgets to the status bar:
        # Status:
        self.statusbar.AddWidget(self.status_text, ESB.ESB_ALIGN_CENTER_HORIZONTAL, ESB.ESB_ALIGN_CENTER_VERTICAL)

        # Placer 1:
        self.statusbar.AddWidget(placer1)

        # Title:
        #self.statusbar.AddWidget(measurement_text, ESB.ESB_ALIGN_CENTER_HORIZONTAL, ESB.ESB_ALIGN_CENTER_VERTICAL)

        # Placer 2
        self.statusbar.AddWidget(placer2)

        # Version:
        self.statusbar.AddWidget(version_label, ESB.ESB_ALIGN_CENTER_HORIZONTAL, ESB.ESB_ALIGN_CENTER_VERTICAL)

    #end def

    #--------------------------------------------------------------------------
    def update_statusbar(self, msg):
        string = msg

        # Status:
        if string == 'Running' or string == 'Finished, Ready' or string == 'Exception Occurred':
            self.status_text.SetLabel(string)
            self.status_text.SetBackgroundColour(wx.NullColour)

            if string == 'Exception Occurred':
                self.status_text.SetBackgroundColour("RED")
            #end if

        #end if

    #end def

#end class
###############################################################################

###############################################################################
class App(wx.App):
    """
    App for initializing program
    """
    #--------------------------------------------------------------------------
    def OnInit(self):
        self.frame = Frame(parent=None, title="Hot Press Status GUI", size=(1280,1280))
        self.frame.Show()

        setup = Setup()
        return True
    #end init

#end class
###############################################################################

# Conversion Functions for voltage to temperature conversion

voltsToTemp1 = (0.0E0,
                2.5173462E1,
                -1.1662878E0,
                -1.0833638E0,
                -8.977354E-1,
                -3.7342377E-1,
                -8.6632643E-2,
                -1.0450598E-2,
                -5.1920577E-4)

voltsToTemp2 = (0.0E0,
                2.508355E1,
                7.860106E-2,
                -2.503131E-1,
                8.31527E-2,
                -1.228034E-2,
                9.804036E-4,
                -4.41303E-5,
                1.057734E-6,
                -1.052755E-8)

voltsToTemp3 = (-1.318058E2,
                4.830222E1,
                -1.646031E0,
                5.464731E-2,
                -9.650715E-4,
                8.802193E-6,
                -3.11081E-8)

def voltsToTempConstants(mVolts):
    if mVolts < -5.891 or mVolts > 54.886:
        raise Exception("Invalid range")
    if mVolts < 0:
        return voltsToTemp1
    elif mVolts < 20.644:
        return voltsToTemp2
    else:
        return voltsToTemp3

tempToVolts1 = (0.0E0,
                0.39450128E-1,
                0.236223736E-4,
                -0.328589068E-6,
                -0.499048288E-8,
                -0.675090592E-10,
                -0.574103274E-12,
                -0.310888729E-14,
                -0.104516094E-16,
                -0.198892669E-19,
                -0.163226975E-22)


class ExtendedList(list):
    pass

tempToVolts2 = ExtendedList()
tempToVolts2.append(-0.176004137E-1)
tempToVolts2.append(0.38921205E-1)
tempToVolts2.append(0.1855877E-4)
tempToVolts2.append(-0.994575929E-7)
tempToVolts2.append(0.318409457E-9)
tempToVolts2.append(-0.560728449E-12)
tempToVolts2.append(0.560750591E-15)
tempToVolts2.append(-0.3202072E-18)
tempToVolts2.append(0.971511472E-22)
tempToVolts2.append(-0.121047213E-25)
tempToVolts2.extended = (0.1185976E0, -0.1183432E-3, 0.1269686E3)


def tempToVoltsConstants(tempC):
    if tempC < -270 or tempC > 1372:
        raise Exception("Invalid range")
    if tempC < 0:
        return tempToVolts1
    else:
        return tempToVolts2

def evaluatePolynomial(coeffs, x):
    sum = 0
    y = 1
    for a in coeffs:
        sum += y * a
        y *= x
    return sum


def tempCToMVolts(tempC):
    coeffs = tempToVoltsConstants(tempC)
    if hasattr(coeffs, "extended"):
        a0, a1, a2 = coeffs.extended
        import math
        extendedCalc = a0 * math.exp(a1 * (tempC - a2) * (tempC - a2))
        return evaluatePolynomial(coeffs, tempC) + extendedCalc
    else:
        return evaluatePolynomial(coeffs, tempC)

def mVoltsToTempC(mVolts):
    coeffs = voltsToTempConstants(mVolts)
    temp = float(evaluatePolynomial(coeffs, mVolts))
    return temp

#==============================================================================
if __name__=='__main__':
    app = App()
    app.MainLoop()

#end if
