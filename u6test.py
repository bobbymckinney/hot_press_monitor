from time import sleep

import u6


if __name__ == '__main__':
    d = u6.U6()

    for i in range(10):

        Volts = d.getAIN(4, resolutionIndex = 8, gainIndex = 15)

        print "Voltage:", Volts

        sleep(1)
